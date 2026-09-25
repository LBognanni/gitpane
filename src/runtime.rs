use std::fs::{self, OpenOptions};
use std::io::{self, ErrorKind};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::thread;
use std::time::Instant;

use ratatui::DefaultTerminal;

use crate::app::{App, Effect, Event, Job};
use crate::git::GitApi;
use crate::ui;

/// The platform location of the first-launch marker, if one can be determined.
pub fn default_marker() -> Option<PathBuf> {
    let dirs = directories::ProjectDirs::from("", "", "gitpane")?;
    let dir = dirs.state_dir().unwrap_or_else(|| dirs.data_local_dir());
    Some(dir.join("shortcuts-shown"))
}

/// Claim the first launch by creating `marker`; true when the shortcuts should show.
pub fn claim_first_launch(marker: &Path) -> bool {
    if let Some(parent) = marker.parent()
        && fs::create_dir_all(parent).is_err()
    {
        return true;
    }
    match OpenOptions::new().write(true).create_new(true).open(marker) {
        Err(error) => error.kind() != ErrorKind::AlreadyExists,
        Ok(_) => true,
    }
}

/// Run one background job to completion and return its result event.
pub fn run_job(git: &dyn GitApi, job: Job) -> Event {
    match job {
        Job::Status(root) => Event::Status(git.status(&root)),
    }
}

/// Forwards terminal input to the event channel until the receiver is gone.
fn spawn_input(tx: Sender<Event>) {
    thread::spawn(move || {
        while let Ok(input) = crossterm::event::read() {
            if tx.send(Event::Input(input)).is_err() {
                break;
            }
        }
    });
}

/// The FIFO Git queue: runs jobs in order and posts their results.
fn spawn_git(git: Arc<dyn GitApi>, tx: Sender<Event>) -> Sender<Job> {
    let (jobs, rx) = mpsc::channel::<Job>();
    thread::spawn(move || {
        for job in rx {
            if tx.send(run_job(git.as_ref(), job)).is_err() {
                break;
            }
        }
    });
    jobs
}

pub fn run(terminal: &mut DefaultTerminal, git: Arc<dyn GitApi>, mut app: App) -> io::Result<()> {
    let (tx, rx) = mpsc::channel();
    spawn_input(tx.clone());
    let jobs = spawn_git(git, tx);
    terminal.draw(|frame| ui::render(&mut app, frame))?;
    if execute(app.start(), &jobs) {
        return Ok(());
    }
    loop {
        let first = match app.deadline() {
            Some(deadline) => {
                match rx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
                    Ok(event) => event,
                    Err(RecvTimeoutError::Timeout) => Event::Tick(Instant::now()),
                    Err(RecvTimeoutError::Disconnected) => return Ok(()),
                }
            }
            None => match rx.recv() {
                Ok(event) => event,
                Err(_) => return Ok(()),
            },
        };
        if apply(&mut app, first, &rx, &jobs) {
            return Ok(());
        }
        terminal.draw(|frame| ui::render(&mut app, frame))?;
    }
}

/// Applies `first` and every queued event; returns true when the app should quit.
fn apply(app: &mut App, first: Event, rx: &Receiver<Event>, jobs: &Sender<Job>) -> bool {
    for event in std::iter::once(first).chain(rx.try_iter()) {
        if execute(app.update(event), jobs) {
            return true;
        }
    }
    // Continuous input never times out the wait, so expire toasts here too.
    app.expire_due(Instant::now());
    false
}

/// Executes effects; returns true when one of them is `Quit`.
fn execute(effects: Vec<Effect>, jobs: &Sender<Job>) -> bool {
    for effect in effects {
        match effect {
            Effect::Quit => return true,
            Effect::Git(job) => {
                let _ = jobs.send(job);
            }
        }
    }
    false
}

use std::io;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;

use ratatui::DefaultTerminal;

use crate::app::{App, Effect, Event};
use crate::ui;

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

pub fn run(terminal: &mut DefaultTerminal) -> io::Result<()> {
    let (tx, rx) = mpsc::channel();
    spawn_input(tx);
    let mut app = App::default();
    terminal.draw(|frame| ui::render(&mut app, frame))?;
    while let Ok(event) = rx.recv() {
        if apply(&mut app, event, &rx) {
            return Ok(());
        }
        terminal.draw(|frame| ui::render(&mut app, frame))?;
    }
    Ok(())
}

/// Applies `first` and every queued event; returns true when the app should quit.
fn apply(app: &mut App, first: Event, rx: &Receiver<Event>) -> bool {
    for event in std::iter::once(first).chain(rx.try_iter()) {
        if app.update(event).contains(&Effect::Quit) {
            return true;
        }
    }
    false
}

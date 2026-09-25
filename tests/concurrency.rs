mod common;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver, Sender};

use common::{FakeGit, Harness, ROOT, state};
use crossterm::event::KeyCode;
use gitpane::app::{Action, Event, Job};
use gitpane::model::{FileEntry, Side};
use gitpane::runtime;

fn status_job(token: u64) -> Job {
    Job::Status {
        root: PathBuf::from(ROOT),
        token,
    }
}

fn stage_job(path: &str, token: u64) -> Job {
    Job::Mutate {
        root: PathBuf::from(ROOT),
        action: Action::Stage,
        entries: vec![FileEntry::new(path, Side::Unstaged, 'M')],
        token,
    }
}

/// A running Git queue over a gated fake.
struct Queue {
    git: Arc<FakeGit>,
    jobs: Sender<Job>,
    events: Receiver<Event>,
    started: Receiver<String>,
    release: Sender<()>,
}

impl Queue {
    fn new() -> Self {
        let (git, started, release) = FakeGit::gated(Ok(state(&[], &[])));
        let git = Arc::new(git);
        let (tx, events) = mpsc::channel();
        let jobs = runtime::spawn_git(git.clone(), tx);
        Self {
            git,
            jobs,
            events,
            started,
            release,
        }
    }

    /// Wait for the next Git call to start and return it; it stays blocked.
    fn next_call(&self) -> String {
        self.started.recv().unwrap()
    }

    fn release(&self) {
        self.release.send(()).unwrap();
    }

    fn token(&self) -> u64 {
        match self.events.recv().unwrap() {
            Event::Status { token, .. } => token,
            other => panic!("unexpected event {other:?}"),
        }
    }
}

#[test]
fn status_refresh_runs_git_off_the_event_thread() {
    // The app only queues the read; the lists show loading meanwhile.
    let mut harness = Harness::held(Ok(state(&[], &[])));
    assert!(harness.git.calls().is_empty());
    let screen = harness.screen();
    assert_eq!(screen.matches("Loading…").count(), 2, "{screen}");

    // The queue runs the read on its own thread: this thread keeps running
    // while the read is blocked inside Git.
    let queue = Queue::new();
    queue.jobs.send(status_job(1)).unwrap();
    assert_eq!(queue.next_call(), "status /repo");
    queue.release();
    assert_eq!(queue.token(), 1);

    let mut worker = state(&[], &[]);
    worker.branch = "worker".to_string();
    *harness.git.status.lock().unwrap() = Ok(worker);
    let result = harness.run_next();
    harness.send(result);
    assert_eq!(harness.line(29).trim(), "Branch: worker");
    assert!(!harness.screen().contains("Loading…"));
}

/// Start held, queue a second read with `r`, and run both reads with
/// different results: returns (older, newer) result events.
fn two_reads(harness: &mut Harness) -> (Event, Event) {
    harness.press(KeyCode::Char('r'));
    let mut older = state(&["old.txt"], &[]);
    older.branch = "older".to_string();
    *harness.git.status.lock().unwrap() = Ok(older);
    let first = harness.run_next();
    let mut newer = state(&[], &["new.txt"]);
    newer.branch = "newer".to_string();
    *harness.git.status.lock().unwrap() = Ok(newer);
    let second = harness.run_next();
    (first, second)
}

#[test]
fn superseded_refresh_results_are_never_displayed() {
    let mut harness = Harness::held(Ok(state(&[], &[])));
    let (older, newer) = two_reads(&mut harness);

    harness.send(older);
    let screen = harness.screen();
    assert!(!screen.contains("older"), "{screen}");
    assert!(!screen.contains("old.txt"));
    assert_eq!(screen.matches("Loading…").count(), 2);

    harness.send(newer);
    let screen = harness.screen();
    assert_eq!(harness.line(29).trim(), "Branch: newer");
    assert!(screen.contains("[ ] M new.txt"));
    assert!(!screen.contains("old.txt"));
}

#[test]
fn newest_result_wins_when_results_complete_out_of_order() {
    let mut harness = Harness::held(Ok(state(&[], &[])));
    let (older, newer) = two_reads(&mut harness);

    harness.send(newer);
    harness.send(older);
    let screen = harness.screen();
    assert_eq!(harness.line(29).trim(), "Branch: newer");
    assert!(screen.contains("[ ] M new.txt"));
    assert!(!screen.contains("old.txt"));
}

#[test]
fn repeated_status_refreshes_do_not_overlap() {
    let queue = Queue::new();
    queue.jobs.send(status_job(1)).unwrap();
    queue.jobs.send(status_job(2)).unwrap();
    assert_eq!(queue.next_call(), "status /repo");
    // The first read is still blocked, so the second has not started.
    assert_eq!(queue.git.calls(), ["status /repo"]);
    queue.release();
    assert_eq!(queue.token(), 1);
    assert_eq!(queue.next_call(), "status /repo");
    queue.release();
    assert_eq!(queue.token(), 2);
    assert_eq!(queue.git.calls().len(), 2);
}

#[test]
fn mutations_are_serialized_and_no_status_read_interleaves() {
    let queue = Queue::new();
    queue.jobs.send(stage_job("one.txt", 1)).unwrap();
    queue.jobs.send(status_job(2)).unwrap();
    queue.jobs.send(stage_job("two.txt", 3)).unwrap();

    assert_eq!(queue.next_call(), "stage one.txt");
    assert_eq!(queue.git.calls(), ["stage one.txt"]);
    queue.release();
    // The mutation job's own status read runs before the queued read.
    assert_eq!(queue.next_call(), "status /repo");
    queue.release();
    assert_eq!(queue.token(), 1);
    assert_eq!(queue.next_call(), "status /repo");
    queue.release();
    assert_eq!(queue.token(), 2);
    assert_eq!(queue.next_call(), "stage two.txt");
    queue.release();
    assert_eq!(queue.next_call(), "status /repo");
    queue.release();
    assert_eq!(queue.token(), 3);
    assert_eq!(
        queue.git.calls(),
        [
            "stage one.txt",
            "status /repo",
            "status /repo",
            "stage two.txt",
            "status /repo",
        ]
    );
}

#[test]
fn mutations_are_queued_in_request_order_and_the_last_result_wins() {
    let mut harness = Harness::held(Ok(state(&[], &["one.txt", "two.txt"])));
    let startup = harness.run_next();
    harness.send(startup);

    harness.press(KeyCode::Char('s'));
    harness.press(KeyCode::Down);
    harness.press(KeyCode::Char('s'));
    assert_eq!(harness.git.calls(), ["status /repo"]);
    assert_eq!(harness.screen().matches("Loading…").count(), 2);

    *harness.git.status.lock().unwrap() = Ok(state(&["one.txt"], &["two.txt"]));
    let first = harness.run_next();
    *harness.git.status.lock().unwrap() = Ok(state(&["one.txt", "two.txt"], &[]));
    let second = harness.run_next();
    assert_eq!(
        harness.git.calls()[1..],
        [
            "stage one.txt",
            "status /repo",
            "stage two.txt",
            "status /repo"
        ]
    );

    // The first mutation's read was superseded by the second request.
    harness.send(first);
    assert_eq!(harness.screen().matches("Loading…").count(), 2);
    harness.send(second);
    let screen = harness.screen();
    assert!(screen.contains("[ ] M one.txt"));
    assert!(screen.contains("[ ] M two.txt"));
    assert!(!screen.contains("Loading…"));
}

mod common;

use std::time::{Duration, Instant};

use common::{Harness, TempDir, state};
use crossterm::event::{KeyCode, KeyModifiers};
use gitpane::app::{Event, Focus, Severity, Tab};
use gitpane::git::GitError;
use gitpane::runtime::{claim_first_launch, default_marker};
use ratatui::style::Modifier;

/// The label of the bold tab in the tabs row.
fn active_tab(harness: &Harness) -> String {
    let buffer = harness.buffer();
    let row = harness.line(0);
    let bold: String = row
        .chars()
        .enumerate()
        .filter(|(x, _)| buffer[(*x as u16, 0)].modifier.contains(Modifier::BOLD))
        .map(|(_, c)| c)
        .collect();
    bold.trim().to_string()
}

fn shortcuts_open(harness: &Harness) -> bool {
    harness.find("Keyboard Shortcuts").is_some()
}

fn failure(stderr: &str) -> GitError {
    GitError::Failed {
        code: Some(128),
        stderr: stderr.to_string(),
    }
}

#[test]
fn starts_on_changes_tab_with_status_and_branch() {
    let harness = Harness::new(Ok(state(&["staged.txt"], &["notes.txt"])));
    assert_eq!(active_tab(&harness), "Changes");
    let screen = harness.screen();
    for text in [
        "Staged",
        "Unstaged",
        "Commits",
        "[ ] M staged.txt",
        "[ ] M notes.txt",
    ] {
        assert!(screen.contains(text), "{text:?} missing:\n{screen}");
    }
    assert_eq!(harness.line(29).trim(), "Branch: main");
    assert_eq!(*harness.git.calls.lock().unwrap(), ["status /repo"]);
    assert_eq!(harness.app.focus, Focus::Staged);
}

#[test]
fn startup_focuses_unstaged_when_nothing_is_staged() {
    let harness = Harness::new(Ok(state(&[], &["notes.txt"])));
    assert_eq!(harness.app.focus, Focus::Unstaged);
}

#[test]
fn status_failure_shows_an_error_toast_that_expires() {
    let mut harness = Harness::new(Err(failure("fatal: bad index")));
    let screen = harness.screen();
    assert!(screen.contains("Could not refresh status"));
    assert!(screen.contains("fatal: bad index"));
    assert!(!screen.contains("Loading…"));

    harness.send(Event::Tick(Instant::now()));
    assert!(harness.find("fatal: bad index").is_some());
    harness.send(Event::Tick(Instant::now() + Duration::from_secs(6)));
    assert!(harness.find("fatal: bad index").is_none());
}

#[test]
fn clicking_a_toast_dismisses_it() {
    let mut harness = Harness::new(Err(failure("fatal: bad index")));
    let position = harness.at("fatal: bad index");
    harness.click(position);
    assert!(harness.find("fatal: bad index").is_none());
}

#[test]
fn toasts_wrap_long_text_within_fifty_columns() {
    let message = "word ".repeat(30);
    let harness = Harness::new(Err(failure(&message)));
    let (x, y) = harness.at("Could not refresh status");
    assert!(x >= 100 - 50);
    // The body wraps onto several rows beneath the title.
    assert!(harness.line(y + 1).contains("word word"));
    assert!(harness.line(y + 2).contains("word word"));
}

#[test]
fn number_keys_switch_tabs_and_focus() {
    let mut harness = Harness::new(Ok(state(&["first.txt"], &["unstaged.txt"])));
    harness.press(KeyCode::Char('2'));
    assert_eq!(active_tab(&harness), "Files");
    assert_eq!(harness.app.focus, Focus::FilesTree);
    harness.press(KeyCode::Char('1'));
    assert_eq!(active_tab(&harness), "Changes");
    assert_eq!(harness.app.focus, Focus::Staged);
}

#[test]
fn changes_key_focuses_the_first_non_empty_section() {
    let mut harness = Harness::new(Ok(state(&[], &["unstaged.txt"])));
    harness.press(KeyCode::Tab);
    harness.press(KeyCode::Char('1'));
    assert_eq!(harness.app.focus, Focus::Unstaged);

    let mut harness = Harness::new(Ok(state(&[], &[])));
    harness.press(KeyCode::Char('1'));
    assert_eq!(harness.app.focus, Focus::Commits);
}

#[test]
fn tab_and_shift_tab_cycle_panes_of_the_active_tab() {
    let mut harness = Harness::new(Ok(state(&["a.txt"], &["b.txt"])));
    let mut seen = Vec::new();
    for _ in 0..4 {
        harness.press(KeyCode::Tab);
        seen.push(harness.app.focus);
    }
    assert_eq!(
        seen,
        [Focus::Unstaged, Focus::Commits, Focus::Diff, Focus::Staged]
    );
    harness.press(KeyCode::BackTab);
    assert_eq!(harness.app.focus, Focus::Diff);

    harness.press(KeyCode::Char('2'));
    harness.press(KeyCode::Tab);
    assert_eq!(harness.app.focus, Focus::Preview);
    harness.press(KeyCode::Tab);
    assert_eq!(harness.app.focus, Focus::FilesTree);
}

#[test]
fn clicking_tabs_and_panes_moves_focus() {
    let mut harness = Harness::new(Ok(state(&["a.txt"], &["b.txt"])));
    harness.click(harness.at("b.txt"));
    assert_eq!(harness.app.focus, Focus::Unstaged);
    harness.click((70, 15));
    assert_eq!(harness.app.focus, Focus::Diff);

    harness.click(harness.at("Files"));
    assert_eq!(harness.app.tab, Tab::Files);
    assert_eq!(harness.app.focus, Focus::FilesTree);
    harness.click((70, 15));
    assert_eq!(harness.app.focus, Focus::Preview);

    harness.click(harness.at("Changes"));
    assert_eq!(active_tab(&harness), "Changes");
}

#[test]
fn focused_list_border_uses_a_distinct_color() {
    let mut harness = Harness::new(Ok(state(&["a.txt"], &["b.txt"])));
    let (_, staged_row) = harness.at("a.txt");
    let (_, unstaged_row) = harness.at("b.txt");
    let border = |harness: &Harness, row: u16| harness.buffer()[(0, row)].fg;
    let focused = border(&harness, staged_row);
    assert_ne!(focused, border(&harness, unstaged_row));
    harness.press(KeyCode::Tab);
    assert_eq!(border(&harness, unstaged_row), focused);
    assert_ne!(border(&harness, staged_row), focused);
}

#[test]
fn hovering_a_button_shows_its_hint_in_the_status_bar() {
    let mut harness = Harness::new(Ok(state(&[], &[])));
    let (x, y) = harness.at("↑");
    harness.hover((x, y));
    assert_eq!(harness.line(29).trim(), "Previous Change");
    harness.hover((x + 3, y));
    assert_eq!(harness.line(29).trim(), "Next Change");
    harness.hover((70, 15));
    assert_eq!(harness.line(29).trim(), "Branch: main");
}

#[test]
fn q_and_ctrl_c_quit() {
    let mut harness = Harness::new(Ok(state(&[], &[])));
    harness.press(KeyCode::Char('c'));
    assert!(!harness.quit);
    harness.press(KeyCode::Char('q'));
    assert!(harness.quit);

    let mut harness = Harness::new(Ok(state(&[], &[])));
    harness.press_with(KeyCode::Char('c'), KeyModifiers::CONTROL);
    assert!(harness.quit);
}

#[test]
fn shortcut_popup_opens_on_first_launch_and_with_h() {
    let mut harness = Harness::with(Ok(state(&[], &[])), true, 100, 30);
    assert!(shortcuts_open(&harness));
    let screen = harness.screen();
    assert!(screen.contains("Mouse controls are supported throughout."));
    assert!(screen.contains("s           Stage or unstage"));
    // The dialog is 60 columns wide, border included.
    let (x, y) = harness.at("Keyboard Shortcuts");
    let top: Vec<char> = harness.line(y - 2).chars().collect();
    let left = top[..x as usize].iter().rposition(|c| *c == '┌').unwrap();
    let right = left + top[left..].iter().position(|c| *c == '┐').unwrap();
    assert_eq!(right - left + 1, 60);

    harness.press(KeyCode::Char('h'));
    assert!(!shortcuts_open(&harness));
    harness.press(KeyCode::Char('h'));
    assert!(shortcuts_open(&harness));
    harness.press(KeyCode::Esc);
    assert!(!shortcuts_open(&harness));
    harness.press(KeyCode::Char('h'));
    harness.press(KeyCode::Enter);
    assert!(!shortcuts_open(&harness));
    harness.press(KeyCode::Char('h'));
    harness.click(harness.at("Close"));
    assert!(!shortcuts_open(&harness));
}

#[test]
fn shortcut_popup_is_absent_when_not_first_launch() {
    let harness = Harness::new(Ok(state(&[], &[])));
    assert!(!shortcuts_open(&harness));
}

#[test]
fn modal_captures_keys_and_clicks() {
    let mut harness = Harness::with(Ok(state(&["a.txt"], &["b.txt"])), true, 100, 30);
    harness.press(KeyCode::Char('2'));
    harness.press(KeyCode::Tab);
    harness.press(KeyCode::Char('q'));
    assert!(!harness.quit);
    harness.click(harness.at("Files"));
    harness.click((0, 29));
    assert_eq!(harness.app.tab, Tab::Changes);
    assert_eq!(harness.app.focus, Focus::Staged);
    assert!(shortcuts_open(&harness));
}

#[test]
fn modal_dims_the_screen_behind_it() {
    let mut harness = Harness::new(Ok(state(&[], &[])));
    let before = harness.buffer()[(1, 29)].bg;
    harness.press(KeyCode::Char('h'));
    assert_ne!(harness.buffer()[(1, 29)].bg, before);
}

#[test]
fn claim_first_launch_accepts_an_isolated_marker_path() {
    let dir = TempDir::new("isolated-marker");
    let marker = dir.0.join("state").join("welcome-shown");
    assert!(claim_first_launch(&marker));
    assert!(marker.is_file());
    assert!(!claim_first_launch(&marker));
}

#[test]
fn claim_first_launch_shows_help_when_marker_parent_is_invalid() {
    let dir = TempDir::new("invalid-parent");
    let invalid_parent = dir.0.join("not-a-directory");
    std::fs::write(&invalid_parent, "contents").unwrap();
    assert!(claim_first_launch(&invalid_parent.join("shortcuts-shown")));
}

#[test]
fn default_marker_lives_in_the_gitpane_state_directory() {
    let marker = default_marker().unwrap();
    assert!(marker.ends_with("gitpane/shortcuts-shown"), "{marker:?}");
}

#[test]
fn hover_hint_clears_when_the_tab_or_modal_changes() {
    let mut harness = Harness::new(Ok(state(&[], &[])));
    let up = harness.at("↑");
    harness.hover(up);
    harness.press(KeyCode::Char('2'));
    assert_eq!(harness.line(29).trim(), "Branch: main");

    harness.press(KeyCode::Char('1'));
    harness.hover(up);
    harness.press(KeyCode::Char('h'));
    harness.press(KeyCode::Esc);
    assert_eq!(harness.line(29).trim(), "Branch: main");
}

#[test]
fn expired_toasts_disappear_while_input_keeps_arriving() {
    let mut harness = Harness::new(Err(failure("fatal: bad index")));
    harness.app.toasts[0].expires = Instant::now();
    harness.hover((70, 15));
    assert!(harness.find("fatal: bad index").is_none());
}

#[test]
fn clicking_a_toast_dismisses_that_toast_only() {
    let mut harness = Harness::new(Ok(state(&[], &[])));
    for body in ["toast A", "toast B", "toast C"] {
        harness.app.notify(None, body, Severity::Warning);
    }
    harness.draw();
    let b = harness.at("toast B");
    // Only A is due; expire it without redrawing, so the hit map is stale.
    let now = Instant::now();
    harness.app.toasts[0].expires = now;
    harness.app.update(Event::Tick(now));
    harness.click(b);
    assert!(harness.find("toast B").is_none());
    assert!(harness.find("toast C").is_some());
}

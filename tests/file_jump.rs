mod common;

use common::{Harness, TempDir};
use crossterm::event::KeyCode;
use gitpane::app::{Focus, matching_files};

fn index(paths: &[&str]) -> Vec<(String, String)> {
    paths
        .iter()
        .map(|path| (path.to_string(), path.to_lowercase()))
        .collect()
}

// test_matching_files_requires_three_characters_and_matches_case_insensitively
#[test]
fn matching_files_requires_three_characters_and_matches_case_insensitively() {
    let files = index(&["docs/Report.md", "src/reporting.py", "src/other.py"]);
    let expected = vec!["docs/Report.md".to_string(), "src/reporting.py".to_string()];

    assert_eq!(matching_files(&files, "re"), (vec![], false));
    assert_eq!(matching_files(&files, "REP"), (expected.clone(), false));
    assert_eq!(matching_files(&files, "REPO"), (expected, false));
}

// test_matching_files_reports_only_actual_truncation
#[test]
fn matching_files_reports_only_actual_truncation() {
    let names: Vec<String> = (0..100).map(|i| format!("match-{i}.txt")).collect();
    let mut paths: Vec<&str> = names.iter().map(String::as_str).collect();

    let (matches, truncated) = matching_files(&index(&paths), "match");
    assert_eq!(matches.len(), 100);
    assert!(!truncated);

    paths.push("match-extra.txt");
    let (matches, truncated) = matching_files(&index(&paths), "match");
    assert_eq!(matches.len(), 100);
    assert!(truncated);
}

fn jump_open(harness: &Harness) -> bool {
    harness.find("Jump to file").is_some()
}

fn type_text(harness: &mut Harness, text: &str) {
    for c in text.chars() {
        harness.press(KeyCode::Char(c));
    }
}

// test_quick_file_jump_is_memory_backed_and_reveals_nested_file
#[test]
fn quick_file_jump_is_memory_backed_and_reveals_nested_file() {
    let dir = TempDir::new("file-jump");
    let summary = format!("src/reports/summary-{}.py", "x".repeat(80));
    let summer = format!("src/reports/summer-{}.py", "y".repeat(80));
    std::fs::create_dir_all(dir.0.join("src/reports")).unwrap();
    std::fs::write(dir.0.join(&summary), "answer = 42\n").unwrap();
    let mut harness = Harness::launched(&dir.0, &dir.0, &["README.md", &summary, &summer]);
    let files_calls = |h: &Harness| {
        h.git
            .calls()
            .iter()
            .filter(|c| c.starts_with("files"))
            .count()
    };

    // Ignored outside the Files tab, and while the tree loads.
    harness.press(KeyCode::Char('t'));
    assert!(!jump_open(&harness));
    harness.press(KeyCode::Char('2'));
    harness.hold_files = true;
    harness.press(KeyCode::Char('r'));
    harness.press(KeyCode::Char('t'));
    assert!(!jump_open(&harness));
    let files = harness.run_files();
    harness.send(files);
    harness.hold_files = false;
    let calls = files_calls(&harness);

    harness.press(KeyCode::Char('t'));
    let (_, input_row) = harness.at("Jump to file");
    assert_eq!(
        input_row, 4,
        "the dialog border sits three rows from the top"
    );
    assert!(harness.line(0).contains("Changes"), "tabs stay in place");

    type_text(&mut harness, "su");
    assert!(harness.find("summary-").is_none());
    type_text(&mut harness, "m");
    assert!(harness.find("summary-").is_some());
    assert!(harness.find("summer-").is_some());
    // Exactly the two results sit under the input, then the dialog border.
    assert!(harness.line(input_row + 1).contains("summary-"));
    assert!(harness.line(input_row + 2).contains("summer-"));
    assert!(harness.line(input_row + 3).contains("└"));
    assert!(harness.find("Showing first").is_none());

    harness.press(KeyCode::Enter);
    assert!(!jump_open(&harness));
    assert_eq!(harness.app.focus, Focus::FilesTree);
    let screen = harness.screen();
    // Ancestors are expanded and the chosen file is previewed.
    assert!(screen.contains(" src"), "{screen}");
    assert!(screen.contains(" reports"), "{screen}");
    assert!(screen.contains("answer = 42"), "{screen}");
    let title = harness.line(1);
    assert!(title.contains(&summary[..40]), "{title}");
    assert_eq!(
        files_calls(&harness),
        calls,
        "jumping never lists files again"
    );

    // A click outside the dialog cancels, leaving the selection.
    harness.press(KeyCode::Char('t'));
    assert!(jump_open(&harness));
    harness.click((0, 29));
    assert!(!jump_open(&harness));
    harness.press(KeyCode::Char('t'));
    harness.press(KeyCode::Esc);
    assert!(!jump_open(&harness));
    assert!(harness.screen().contains("answer = 42"));
}

#[test]
fn down_moves_into_results_and_enter_picks_the_highlighted_one() {
    let dir = TempDir::new("file-jump-down");
    std::fs::write(dir.0.join("beta-two.txt"), "second file\n").unwrap();
    let mut harness = Harness::launched(&dir.0, &dir.0, &["beta-one.txt", "beta-two.txt"]);
    harness.press(KeyCode::Char('2'));
    harness.press(KeyCode::Char('t'));
    type_text(&mut harness, "beta");
    harness.press(KeyCode::Down);
    harness.press(KeyCode::Down);
    harness.press(KeyCode::Enter);
    assert!(harness.screen().contains("second file"));
}

#[test]
fn clicking_a_result_jumps_to_it_and_backspace_edits_the_query() {
    let dir = TempDir::new("file-jump-click");
    std::fs::write(dir.0.join("gamma.txt"), "gamma body\n").unwrap();
    let mut harness = Harness::launched(&dir.0, &dir.0, &["gamma.txt"]);
    harness.press(KeyCode::Char('2'));
    harness.press(KeyCode::Char('t'));
    type_text(&mut harness, "gamx");
    assert!(harness.find("gamx").is_some());
    harness.press(KeyCode::Backspace);
    // The dialog's input is row 4; the first result is below it.
    assert!(harness.line(5).contains("gamma.txt"));
    harness.click((50, 5));
    assert!(!jump_open(&harness));
    assert!(harness.screen().contains("gamma body"));
}

#[test]
fn more_than_a_hundred_matches_shows_the_truncation_note() {
    let names: Vec<String> = (0..101).map(|i| format!("match-{i:03}.txt")).collect();
    let paths: Vec<&str> = names.iter().map(String::as_str).collect();
    let mut harness = Harness::launched(
        std::path::Path::new("/repo"),
        std::path::Path::new("/repo"),
        &paths,
    );
    harness.press(KeyCode::Char('2'));
    harness.press(KeyCode::Char('t'));
    type_text(&mut harness, "match");
    assert!(harness.find("Showing first 100 matches").is_some());
}

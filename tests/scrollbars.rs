//! Scrollbars on the sidebar lists and trees, shared with the viewers.
mod common;

use common::{Harness, state};
use crossterm::event::{KeyCode, MouseEventKind};
use gitpane::model::Commit;
use ratatui::style::{Color, Modifier};

const LONG_ROOT: &str = "/a/very/long/launch/directory/path/that/overflows";

/// The thumb color at the top of a long diff's vertical scrollbar.
fn viewer_thumb() -> Color {
    let mut patch = String::from("--- a/a.txt\n+++ b/a.txt\n@@ -1,100 +1,100 @@\n");
    for _ in 0..100 {
        patch.push_str(" line\n");
    }
    let mut harness = Harness::new(Ok(state(&[], &["a.txt"])));
    harness.git.set_diff("a.txt", Ok(patch));
    harness.press(KeyCode::Enter);
    let view = harness.app.diff_view.viewport();
    harness.buffer()[(view.right(), view.y)].bg
}

fn files_tab(root: &str, count: usize) -> Harness {
    let files: Vec<String> = (0..count).map(|i| format!("file{i:02}.txt")).collect();
    let files: Vec<&str> = files.iter().map(String::as_str).collect();
    let root = std::path::Path::new(root);
    let mut harness = Harness::launched(root, root, &files);
    harness.press(KeyCode::Char('2'));
    harness
}

fn bg(harness: &Harness, position: (u16, u16)) -> Color {
    harness.buffer()[position].bg
}

/// The last column inside the list or tree border at `row`.
fn bar_column(harness: &Harness, row: u16) -> u16 {
    let line: Vec<char> = harness.line(row).chars().collect();
    let right = (1..line.len()).find(|&x| line[x] == '│').unwrap();
    right as u16 - 1
}

#[test]
fn scrollbar_thumbs_share_one_blue_color() {
    let thumb = viewer_thumb();
    let Color::Rgb(r, _, b) = thumb else {
        panic!("expected an RGB thumb, got {thumb:?}");
    };
    // A light blue like the Python app's, not a grey.
    assert!(b > r.saturating_add(64), "{thumb:?}");
    let harness = files_tab("/repo", 40);
    let x = bar_column(&harness, 3);
    assert_eq!(bg(&harness, (x, 3)), thumb);
}

#[test]
fn files_tree_shows_scrollbars_only_when_it_overflows() {
    let small = files_tab("/repo", 3);
    let x = bar_column(&small, 4);
    assert_eq!(bg(&small, (x, 4)), bg(&small, (x - 5, 4)));
    let bottom = small.find("└──").unwrap().1 - 1;
    assert_eq!(bg(&small, (1, bottom)), bg(&small, (5, bottom)));

    let thumb = viewer_thumb();
    let tall = files_tab("/repo", 40);
    assert_eq!(bg(&tall, (x, 4)), thumb, "vertical thumb");
    let wide = files_tab(LONG_ROOT, 3);
    let bottom = wide.find("└──").unwrap().1 - 1;
    assert_eq!(bg(&wide, (1, bottom)), thumb, "horizontal thumb");
}

#[test]
fn wheel_scrolls_the_files_tree_without_moving_the_cursor() {
    let mut harness = files_tab(LONG_ROOT, 40);
    assert!(harness.line(3).contains("/a/very"));
    harness.scroll(MouseEventKind::ScrollDown, (10, 10));
    assert!(
        harness.line(3).contains("file02.txt"),
        "{}",
        harness.screen()
    );
    let x = bar_column(&harness, 3);
    assert_ne!(bg(&harness, (x, 3)), viewer_thumb(), "the thumb moved down");
    harness.scroll(MouseEventKind::ScrollUp, (10, 10));
    harness.scroll(MouseEventKind::ScrollRight, (10, 10));
    harness.scroll(MouseEventKind::ScrollRight, (10, 10));
    assert!(!harness.line(3).contains("/a/very"), "{}", harness.screen());
    assert!(harness.line(3).contains("long"), "{}", harness.screen());

    // The cursor stayed on the root: the next key moves it to the first file
    // and scrolls that row into view (cut by the horizontal scroll).
    harness.scroll(MouseEventKind::ScrollDown, (10, 10));
    harness.scroll(MouseEventKind::ScrollDown, (10, 10));
    harness.press(KeyCode::Char('j'));
    assert!(
        harness.line(3).contains("ile00.txt"),
        "{}",
        harness.screen()
    );
}

#[test]
fn commit_tree_and_status_lists_show_scrollbars_when_they_overflow() {
    let unstaged: Vec<String> = (0..40).map(|i| format!("file{i:02}.txt")).collect();
    let unstaged: Vec<&str> = unstaged.iter().map(String::as_str).collect();
    let mut harness = Harness::new(Ok(state(&[], &unstaged)));
    let commits: Vec<Commit> = (0..40)
        .map(|i| Commit {
            hash: format!("{i:040}"),
            short_hash: format!("{i:07}"),
            parent: None,
            subject: format!("Commit {i:02} with a subject far too long for the sidebar"),
        })
        .collect();
    *harness.git.commits.lock().unwrap() = Ok(commits);
    harness.press(KeyCode::Char('r'));
    let thumb = viewer_thumb();

    let (_, row) = harness.at("file00.txt");
    assert_eq!(bg(&harness, (bar_column(&harness, row), row)), thumb);

    let (_, row) = harness.at("Commit 00");
    assert_eq!(bg(&harness, (bar_column(&harness, row), row)), thumb);
    let bottom = (row..30)
        .find(|&y| harness.line(y).starts_with('└'))
        .unwrap()
        - 1;
    assert_eq!(bg(&harness, (1, bottom)), thumb, "horizontal thumb");
}

#[test]
fn section_splitters_sit_on_the_sidebar_surface() {
    let harness = Harness::new(Ok(state(&["a.txt"], &["b.txt", "c.txt"])));
    let (_, title) = harness.at("Unstaged");
    let splitter = (5, title - 1);
    assert_eq!(harness.buffer()[splitter].symbol(), "─");
    // An unhighlighted row shows the sidebar's surface.
    let row = harness.at("c.txt");
    assert_eq!(bg(&harness, splitter), bg(&harness, row));
}

#[test]
fn unfocused_tree_cursor_uses_the_inactive_selection() {
    let mut harness = files_tab("/repo", 3);
    let root = harness.at("/repo");
    let focused = harness.buffer()[root].clone();
    harness.press(KeyCode::Tab);
    let unfocused = harness.buffer()[root].clone();
    assert_ne!(unfocused.bg, focused.bg);
    assert_ne!(unfocused.bg, bg(&harness, harness.at("file01.txt")));
    assert!(!unfocused.modifier.contains(Modifier::BOLD));
}

#[test]
fn wide_glyphs_cut_by_the_tree_edge_never_cover_the_border() {
    let mut harness = Harness::new(Ok(state(&[], &[])));
    let commits: Vec<Commit> = (20..32)
        .map(|i| Commit {
            hash: format!("{i:040}"),
            short_hash: format!("{i:07}"),
            parent: None,
            subject: format!("{}🐛🐛", "x".repeat(i)),
        })
        .collect();
    *harness.git.commits.lock().unwrap() = Ok(commits);
    harness.press(KeyCode::Char('r'));
    let (_, first) = harness.at("xxxxxxxxxxxxxxxxxxxx");
    let top: Vec<char> = harness.line(first - 1).chars().collect();
    let border = top.iter().position(|&c| c == '┐').unwrap() as u16;
    for y in (first..).take_while(|&y| !harness.line(y).starts_with('└')) {
        assert_eq!(
            harness.buffer()[(border, y)].symbol(),
            "│",
            "{}",
            harness.screen()
        );
    }
}

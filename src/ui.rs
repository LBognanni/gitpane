use ratatui::Frame;
use ratatui::buffer::Buffer;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Borders, Clear, Padding, Paragraph, Widget};

use crate::app::{
    Action, App, Button, Focus, MAX_FILE_JUMP_RESULTS, Modal, Severity, Tab, Target, TreeRow,
};
use crate::code_view::CodeView;
use crate::icons;
use crate::layout::{Group, Splitter};
use crate::model::{Commit, Side};
use crate::theme;

const TOAST_WIDTH: u16 = 50;
const SHORTCUTS_WIDTH: u16 = 60;
const DISCARD_WIDTH: u16 = 60;
const JUMP_WIDTH: u16 = 70;

pub const SHORTCUTS: &str = "Mouse controls are supported throughout.

Navigation
  j / k       Move selection or scroll
  Enter       Open the selected item
  1 / 2       Changes / Files tab
  n / p       Next / previous diff change
  t           Jump to a file (Files tab)

File actions
  Space       Check or uncheck a file
  s           Stage or unstage the focused file
  d           Discard the focused unstaged file

Application
  r           Refresh repository views
  w           Toggle line wrapping
  h           Show or close this help
  q           Quit";

pub fn render(app: &mut App, frame: &mut Frame) {
    app.hits.clear();
    let area = frame.area();
    let buf = frame.buffer_mut();
    buf.set_style(area, Style::new().fg(theme::TEXT).bg(theme::CANVAS));
    let [tabs, body, status] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Fill(1),
        Constraint::Length(1),
    ])
    .areas(area);

    render_tabs(app, tabs, buf);
    match app.tab {
        Tab::Changes => render_changes(app, body, buf),
        Tab::Files => render_files(app, body, buf),
    }
    let text = match app.hint() {
        Some(hint) => hint.to_string(),
        None => format!("Branch: {}", app.branch),
    };
    Paragraph::new(text)
        .style(theme::title())
        .block(Block::new().padding(Padding::horizontal(1)))
        .render(status, buf);

    if let Some(modal) = app.modal.clone() {
        dim(area, buf);
        app.hits.push((area, Target::Backdrop));
        match modal {
            Modal::Shortcuts => render_shortcuts(app, area, buf),
            Modal::Discard { entries, confirm } => {
                let untracked = entries.iter().any(|entry| entry.status == '?');
                render_discard(app, area, entries.len(), untracked, confirm, buf);
            }
            Modal::FileJump { query, selected } => {
                render_file_jump(app, area, &query, selected, buf)
            }
        }
    }
    render_toasts(
        app,
        Rect {
            height: status.y,
            ..area
        },
        buf,
    );
}

fn render_tabs(app: &mut App, area: Rect, buf: &mut Buffer) {
    buf.set_style(area, Style::new().fg(theme::MUTED_TEXT).bg(theme::SURFACE));
    let mut x = area.x;
    for (tab, label) in [(Tab::Changes, " Changes "), (Tab::Files, " Files ")] {
        let style = if app.tab == tab {
            Style::new()
                .fg(theme::TEXT)
                .bg(theme::RAISED_SURFACE)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::new().fg(theme::MUTED_TEXT).bg(theme::SURFACE)
        };
        let width = (label.len() as u16).min(area.right().saturating_sub(x));
        let rect = Rect::new(x, area.y, width, 1);
        Span::styled(label, style).render(rect, buf);
        app.hits.push((rect, Target::Tab(tab)));
        x += width;
    }
}

/// Split `area` along one axis into the group's panes with one-cell splitters between.
fn split(group: &mut Group, area: Rect, vertical: bool) -> Vec<Rect> {
    let sizes = group.layout(if vertical { area.height } else { area.width });
    let mut constraints = Vec::new();
    for (index, size) in sizes.into_iter().enumerate() {
        if index > 0 {
            constraints.push(Constraint::Length(1));
        }
        constraints.push(Constraint::Length(size));
    }
    let layout = if vertical {
        Layout::vertical(constraints)
    } else {
        Layout::horizontal(constraints)
    };
    layout.split(area).to_vec()
}

fn split_columns(group: &mut Group, area: Rect) -> [Rect; 3] {
    split(group, area, false)
        .try_into()
        .expect("two panes and a splitter")
}

/// Draw a splitter: `│` down a vertical one, `─` across a horizontal one.
fn splitter(app: &mut App, splitter: Splitter, area: Rect, buf: &mut Buffer) {
    let active = app.hover == Some(Target::Splitter(splitter))
        || app.drag.is_some_and(|drag| drag.splitter == splitter);
    let (symbol, color) = (
        match splitter {
            Splitter::Section(_) => "─",
            Splitter::Sidebar | Splitter::Files => "│",
        },
        if active { theme::ACCENT } else { theme::BORDER },
    );
    for position in area.positions() {
        buf[position]
            .set_symbol(symbol)
            .set_fg(color)
            .set_bg(theme::CANVAS);
    }
    app.hits.push((area, Target::Splitter(splitter)));
}

fn render_changes(app: &mut App, area: Rect, buf: &mut Buffer) {
    let [sidebar, divider, pane] = split_columns(&mut app.panes.changes, area);
    splitter(app, Splitter::Sidebar, divider, buf);
    let [staged, split1, unstaged, split2, commits] = split(&mut app.panes.sections, sidebar, true)
        .try_into()
        .expect("three sections and two splitters");
    splitter(app, Splitter::Section(0), split1, buf);
    splitter(app, Splitter::Section(1), split2, buf);

    status_section(app, staged, Side::Staged, buf);
    status_section(app, unstaged, Side::Unstaged, buf);
    let [title, list] =
        Layout::vertical([Constraint::Length(1), Constraint::Fill(1)]).areas(commits);
    viewer_title(app, title, "Commits", &[], buf);
    let loading = app.tree_loading();
    bordered_list(
        app.focus == Focus::Commits,
        loading.then(loading_line).into_iter().collect(),
        list,
        buf,
    );
    app.hits.push((list, Target::Pane(Focus::Commits)));
    if !loading {
        commit_rows(app, list.inner(ratatui::layout::Margin::new(1, 1)), buf);
    }

    let [title, view] = Layout::vertical([Constraint::Length(1), Constraint::Fill(1)]).areas(pane);
    viewer_title(
        app,
        title,
        &app.diff_title.clone(),
        &[Button::PreviousChange, Button::NextChange],
        buf,
    );
    if app.diff_loading {
        Paragraph::new(loading_line())
            .style(Style::new().fg(theme::TEXT).bg(theme::DIFF_BACKGROUND))
            .render(view, buf);
    } else {
        render_view(&mut app.diff_view, view, buf);
    }
    app.hits.push((view, Target::Pane(Focus::Diff)));
}

fn render_files(app: &mut App, area: Rect, buf: &mut Buffer) {
    let [tree, divider, pane] = split_columns(&mut app.panes.files, area);
    splitter(app, Splitter::Files, divider, buf);
    let loading = app.files_tree_loading;
    bordered_list(
        app.focus == Focus::FilesTree,
        loading.then(loading_line).into_iter().collect(),
        tree,
        buf,
    );
    app.hits.push((tree, Target::Pane(Focus::FilesTree)));
    if !loading {
        file_rows(app, tree.inner(ratatui::layout::Margin::new(1, 1)), buf);
    }

    let [title, view] = Layout::vertical([Constraint::Length(1), Constraint::Fill(1)]).areas(pane);
    viewer_title(app, title, &app.preview_title.clone(), &[], buf);
    if app.preview_loading {
        Paragraph::new(loading_line())
            .style(Style::new().fg(theme::TEXT).bg(theme::DIFF_BACKGROUND))
            .render(view, buf);
    } else {
        render_view(&mut app.preview_view, view, buf);
    }
    app.hits.push((view, Target::Pane(Focus::Preview)));
}

fn loading_line() -> Line<'static> {
    Line::styled("Loading…", Style::new().add_modifier(Modifier::DIM))
}

/// A status section: title bar with bulk actions, then the bordered list.
fn status_section(app: &mut App, area: Rect, side: Side, buf: &mut Buffer) {
    let (title, focus, bulk): (_, _, &[Button]) = match side {
        Side::Staged => ("Staged", Focus::Staged, &[Button::Bulk(Action::Unstage)]),
        Side::Unstaged => (
            "Unstaged",
            Focus::Unstaged,
            &[Button::Bulk(Action::Stage), Button::Bulk(Action::Discard)],
        ),
    };
    let [title_row, list] =
        Layout::vertical([Constraint::Length(1), Constraint::Fill(1)]).areas(area);
    let buttons = if app.list(side).any_checked() {
        bulk
    } else {
        &[]
    };
    viewer_title(app, title_row, title, buttons, buf);
    let focused = app.focus == focus;
    let loading = app.status_loading;
    bordered_list(
        focused,
        loading.then(loading_line).into_iter().collect(),
        list,
        buf,
    );
    app.hits.push((list, Target::Pane(focus)));
    if !loading {
        status_rows(
            app,
            side,
            focused,
            list.inner(ratatui::layout::Margin::new(1, 1)),
            buf,
        );
    }
}

/// Draw the visible rows of a status list with their states and row actions.
fn status_rows(app: &mut App, side: Side, focused: bool, area: Rect, buf: &mut Buffer) {
    let height = area.height as usize;
    let list = match side {
        Side::Staged => &mut app.staged,
        Side::Unstaged => &mut app.unstaged,
    };
    if let Some(index) = list.highlight {
        list.offset = list
            .offset
            .min(index)
            .max((index + 1).saturating_sub(height));
    }
    let offset = list.offset;
    let hover = app.hover;
    let list = app.list(side);
    let mut hits = Vec::new();
    for (index, entry) in list.entries.iter().enumerate().skip(offset).take(height) {
        let rect = Rect {
            y: area.y + (index - offset) as u16,
            height: 1,
            ..area
        };
        let highlighted = list.highlight == Some(index);
        let hovered = matches!(
            hover,
            Some(Target::Row(s, i) | Target::Checkbox(s, i) | Target::Button(Button::Row(s, i, _)))
                if s == side && i == index
        );
        let style = if highlighted && focused {
            Style::new()
                .fg(theme::TEXT)
                .bg(theme::FOCUSED_SELECTION)
                .add_modifier(Modifier::BOLD)
        } else if highlighted {
            Style::new().fg(theme::TEXT).bg(theme::INACTIVE_SELECTION)
        } else if hovered {
            Style::new().fg(theme::TEXT).bg(theme::RAISED_SURFACE)
        } else {
            Style::new().fg(theme::TEXT).bg(theme::SURFACE)
        };
        let label = match &entry.unsupported_reason {
            Some(reason) => format!("[!] {} {} - {reason}", entry.status, entry.path),
            None => {
                let mark = if list.checked[index] { 'x' } else { ' ' };
                format!("[{mark}] {} {}", entry.status, entry.path)
            }
        };
        buf.set_style(rect, style);
        Span::styled(label, style).render(rect, buf);
        hits.push((rect, Target::Row(side, index)));
        if entry.unsupported_reason.is_some() {
            continue;
        }
        hits.push((
            Rect {
                width: 3.min(rect.width),
                ..rect
            },
            Target::Checkbox(side, index),
        ));
        if !(hovered || highlighted && focused) {
            continue;
        }
        let actions: &[Action] = match side {
            Side::Staged => &[Action::Unstage],
            Side::Unstaged => &[Action::Stage, Action::Discard],
        };
        let mut x = rect
            .right()
            .saturating_sub(3 * actions.len() as u16)
            .max(rect.x);
        for &action in actions {
            let button = Button::Row(side, index, action);
            let cell = Rect {
                x,
                width: 3.min(rect.right() - x),
                ..rect
            };
            let hovered_button = hover == Some(Target::Button(button));
            Span::styled(glyph(button), button_style(button, hovered_button, style))
                .render(cell, buf);
            hits.push((cell, Target::Button(button)));
            x += cell.width;
        }
    }
    app.hits.extend(hits);
}

/// A commit subject with gitmoji shortcodes expanded, then the short hash in dim text.
pub fn format_commit_label(commit: &Commit) -> Line<'static> {
    Line::from(vec![
        Span::raw(format!("{} ", expand_gitmoji(&commit.subject))),
        Span::styled(
            commit.short_hash.clone(),
            Style::new().add_modifier(Modifier::DIM),
        ),
    ])
}

/// Replace known `:shortcode:`s with their emoji; unknown ones stay as written.
fn expand_gitmoji(text: &str) -> String {
    let mut out = String::new();
    let mut rest = text;
    while let Some(start) = rest.find(':') {
        let after = &rest[start + 1..];
        let found = after
            .find(':')
            .and_then(|end| Some((end, emojis::get_by_shortcode(&after[..end])?)));
        match found {
            Some((end, emoji)) => {
                out.push_str(&rest[..start]);
                out.push_str(emoji.as_str());
                rest = &after[end + 1..];
            }
            None => {
                out.push_str(&rest[..=start]);
                rest = after;
            }
        }
    }
    out.push_str(rest);
    out
}

/// Draw the visible rows of the commit tree.
fn commit_rows(app: &mut App, area: Rect, buf: &mut Buffer) {
    let height = area.height as usize;
    let tree = &mut app.commits;
    let count = tree.rows().len();
    tree.offset = tree.offset.min(count.saturating_sub(height));
    if let Some(cursor) = tree.cursor {
        tree.offset = tree
            .offset
            .min(cursor)
            .max((cursor + 1).saturating_sub(height));
    }
    let tree = &app.commits;
    let mut hits = Vec::new();
    for (index, row) in tree
        .rows()
        .into_iter()
        .enumerate()
        .skip(tree.offset)
        .take(height)
    {
        let rect = Rect {
            y: area.y + (index - tree.offset) as u16,
            height: 1,
            ..area
        };
        let line = match row {
            TreeRow::Commit(commit) => {
                let node = &tree.nodes[commit];
                let mut line = format_commit_label(&node.commit);
                let marker = if node.expanded { "▾ " } else { "▸ " };
                line.spans.insert(0, Span::raw(marker));
                line
            }
            TreeRow::File(commit, file) => {
                let file = &tree.nodes[commit].files.as_ref().expect("loaded files")[file];
                Line::from(format!("    {} {}", file.status, file.path))
            }
            TreeRow::Empty(_) => Line::from("    (no changed files)"),
        };
        let style = if tree.cursor == Some(index) {
            Style::new()
                .fg(theme::TEXT)
                .bg(theme::FOCUSED_SELECTION)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::new().fg(theme::TEXT).bg(theme::SURFACE)
        };
        buf.set_style(rect, style);
        line.style(style).render(rect, buf);
        hits.push((rect, Target::TreeRow(index)));
    }
    app.hits.extend(hits);
}

/// Draw the visible rows of the Files tree.
fn file_rows(app: &mut App, area: Rect, buf: &mut Buffer) {
    let height = area.height as usize;
    let tree = &mut app.files;
    let rows = tree.rows();
    tree.offset = tree.offset.min(rows.len().saturating_sub(height));
    if let Some(cursor) = tree
        .cursor
        .and_then(|node| rows.iter().position(|&r| r == node))
    {
        tree.offset = tree
            .offset
            .min(cursor)
            .max((cursor + 1).saturating_sub(height));
    }
    let tree = &app.files;
    let mut hits = Vec::new();
    for (row, &index) in rows.iter().enumerate().skip(tree.offset).take(height) {
        let rect = Rect {
            y: area.y + (row - tree.offset) as u16,
            height: 1,
            ..area
        };
        let node = &tree.nodes[index];
        let mut line = if node.dir {
            icons::folder_label(&node.name, node.expanded)
        } else {
            icons::file_label(&node.name)
        };
        line.spans
            .insert(0, Span::raw("   ".repeat(node.depth.saturating_sub(1))));
        let style = if tree.cursor == Some(index) {
            Style::new()
                .fg(theme::TEXT)
                .bg(theme::FOCUSED_SELECTION)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::new().fg(theme::TEXT).bg(theme::SURFACE)
        };
        buf.set_style(rect, style);
        line.style(style).render(rect, buf);
        hits.push((rect, Target::FileRow(row)));
    }
    app.hits.extend(hits);
}

/// The three-cell label of an icon button.
fn glyph(button: Button) -> &'static str {
    match button {
        Button::PreviousChange => " ↑ ",
        Button::NextChange => " ↓ ",
        Button::Row(_, _, action) | Button::Bulk(action) => match action {
            Action::Stage => " ↑ ",
            Action::Unstage => " ↓ ",
            Action::Discard => " ↶ ",
        },
    }
}

/// A button's style on `base`: raised and bold while hovered, danger for discard.
fn button_style(button: Button, hovered: bool, base: Style) -> Style {
    if !hovered {
        return base.fg(theme::TEXT);
    }
    let discard = matches!(
        button,
        Button::Row(_, _, Action::Discard) | Button::Bulk(Action::Discard)
    );
    Style::new()
        .fg(if discard { theme::DANGER } else { theme::TEXT })
        .bg(theme::RAISED_SURFACE)
        .add_modifier(Modifier::BOLD)
}

fn bordered_list(focused: bool, rows: Vec<Line<'static>>, area: Rect, buf: &mut Buffer) {
    let border = if focused { theme::FOCUS } else { theme::BORDER };
    Paragraph::new(rows)
        .style(Style::new().fg(theme::TEXT).bg(theme::SURFACE))
        .block(Block::bordered().border_style(Style::new().fg(border)))
        .render(area, buf);
}

/// A title row with `label` on the left and icon `buttons` right-aligned.
fn viewer_title(app: &mut App, area: Rect, label: &str, buttons: &[Button], buf: &mut Buffer) {
    buf.set_style(area, theme::title());
    let inner = area.inner(ratatui::layout::Margin::new(1, 0));
    let actions = (buttons.len() as u16 * 3).min(inner.width);
    let [text, mut rest] =
        Layout::horizontal([Constraint::Fill(1), Constraint::Length(actions)]).areas(inner);
    Paragraph::new(label.to_string())
        .style(theme::title())
        .render(text, buf);
    for &button in buttons {
        let rect = Rect {
            width: 3.min(rest.width),
            ..rest
        };
        let style = if app.enabled(button) {
            button_style(
                button,
                app.hover == Some(Target::Button(button)),
                theme::title(),
            )
        } else {
            theme::title().add_modifier(Modifier::DIM)
        };
        Span::styled(glyph(button), style).render(rect, buf);
        app.hits.push((rect, Target::Button(button)));
        rest.x += rect.width;
        rest.width -= rect.width;
    }
}

fn render_view(view: &mut CodeView, area: Rect, buf: &mut Buffer) {
    view.render(area, buf);
    // CodeView leaves unstyled cells at the terminal default; give them the viewer colors.
    for position in area.positions() {
        let cell = &mut buf[position];
        if cell.fg == Color::Reset {
            cell.fg = theme::TEXT;
        }
        if cell.bg == Color::Reset {
            cell.bg = theme::DIFF_BACKGROUND;
        }
    }
}

/// Blend every cell in `area` 70% toward the canvas color.
fn dim(area: Rect, buf: &mut Buffer) {
    fn blend(color: Color, fallback: Color) -> Color {
        let (Color::Rgb(r, g, b), Color::Rgb(cr, cg, cb)) = (
            if color == Color::Reset {
                fallback
            } else {
                color
            },
            theme::CANVAS,
        ) else {
            return color;
        };
        let mix = |c: u8, k: u8| ((c as u16 * 3 + k as u16 * 7) / 10) as u8;
        Color::Rgb(mix(r, cr), mix(g, cg), mix(b, cb))
    }
    for position in area.positions() {
        let cell = &mut buf[position];
        cell.fg = blend(cell.fg, theme::TEXT);
        cell.bg = blend(cell.bg, theme::CANVAS);
    }
}

fn centered(area: Rect, width: u16, height: u16) -> Rect {
    let width = width.min(area.width);
    let height = height.min(area.height);
    Rect::new(
        area.x + (area.width - width) / 2,
        area.y + (area.height - height) / 2,
        width,
        height,
    )
}

fn render_shortcuts(app: &mut App, area: Rect, buf: &mut Buffer) {
    let lines = SHORTCUTS.lines().count() as u16;
    // Border, padding, title, margins, and the Close button around the text.
    let height = lines + 8;
    let dialog = centered(area, SHORTCUTS_WIDTH.min(area.width * 9 / 10), height);
    Clear.render(dialog, buf);
    let block = Block::bordered()
        .border_style(Style::new().fg(theme::BORDER))
        .style(Style::new().fg(theme::TEXT).bg(theme::RAISED_SURFACE))
        .padding(Padding::new(2, 2, 1, 1));
    let inner = block.inner(dialog);
    block.render(dialog, buf);
    let [text, button] =
        Layout::vertical([Constraint::Fill(1), Constraint::Length(1)]).areas(inner);
    let mut content = vec![
        Line::styled(
            "Keyboard Shortcuts",
            Style::new().add_modifier(Modifier::BOLD),
        ),
        Line::default(),
    ];
    content.extend(SHORTCUTS.lines().map(Line::from));
    Paragraph::new(content).render(text, buf);
    let close = Rect {
        width: 7.min(button.width),
        ..button
    };
    Span::styled(
        " Close ",
        Style::new()
            .fg(theme::TEXT)
            .bg(theme::FOCUSED_SELECTION)
            .add_modifier(Modifier::BOLD),
    )
    .render(close, buf);
    app.hits.push((close, Target::CloseShortcuts));
}

fn render_discard(
    app: &mut App,
    area: Rect,
    count: usize,
    untracked: bool,
    confirm: bool,
    buf: &mut Buffer,
) {
    let noun = if count == 1 { "file" } else { "files" };
    let mut message = format!("Discard changes to {count} {noun}? This cannot be undone.");
    if untracked {
        message.push_str(" Untracked files will be permanently deleted.");
    }
    let width = DISCARD_WIDTH.min(area.width * 9 / 10);
    let text = wrap(&message, width.saturating_sub(6) as usize);
    // Border, padding, title, the message with its margins, and the buttons.
    let dialog = centered(area, width, text.len() as u16 + 8);
    Clear.render(dialog, buf);
    let block = Block::bordered()
        .border_style(Style::new().fg(theme::BORDER))
        .style(Style::new().fg(theme::TEXT).bg(theme::RAISED_SURFACE))
        .padding(Padding::new(2, 2, 1, 1));
    let inner = block.inner(dialog);
    block.render(dialog, buf);
    let [body, buttons] =
        Layout::vertical([Constraint::Fill(1), Constraint::Length(1)]).areas(inner);
    let mut lines = vec![
        Line::styled(
            "Discard Changes?",
            Style::new().add_modifier(Modifier::BOLD),
        ),
        Line::default(),
    ];
    lines.extend(text.into_iter().map(Line::from));
    Paragraph::new(lines).render(body, buf);
    // Right-aligned: ` Cancel `, a gap, then ` Discard `.
    let [_, cancel, _, discard] = Layout::horizontal([
        Constraint::Fill(1),
        Constraint::Length(8),
        Constraint::Length(1),
        Constraint::Length(9),
    ])
    .areas(buttons);
    let focused = |on: bool| {
        if on {
            Modifier::BOLD | Modifier::REVERSED
        } else {
            Modifier::empty()
        }
    };
    Span::styled(
        " Cancel ",
        Style::new()
            .fg(theme::TEXT)
            .bg(theme::INACTIVE_SELECTION)
            .add_modifier(focused(!confirm)),
    )
    .render(cancel, buf);
    Span::styled(
        " Discard ",
        Style::new()
            .fg(theme::CANVAS)
            .bg(theme::DANGER)
            .add_modifier(focused(confirm)),
    )
    .render(discard, buf);
    app.hits.push((cancel, Target::CancelDiscard));
    app.hits.push((discard, Target::ConfirmDiscard));
}

/// The file jump dialog, three rows from the top: input, results, and a truncation note.
fn render_file_jump(
    app: &mut App,
    area: Rect,
    query: &str,
    selected: Option<usize>,
    buf: &mut Buffer,
) {
    let (matches, truncated) = app.jump_matches();
    let top = area.y + 3;
    let available = area.bottom().saturating_sub(top);
    // Borders, the input, and the truncation note surround the results.
    let visible = (matches.len() as u16).min(available.saturating_sub(3 + truncated as u16));
    let height = (visible + 3 + truncated as u16).min(available);
    let width = JUMP_WIDTH.min(area.width);
    let dialog = Rect::new(area.x + (area.width - width) / 2, top, width, height);
    Clear.render(dialog, buf);
    let block = Block::bordered()
        .border_style(Style::new().fg(theme::BORDER))
        .style(Style::new().fg(theme::TEXT).bg(theme::RAISED_SURFACE));
    let inner = block.inner(dialog);
    block.render(dialog, buf);
    app.hits.push((dialog, Target::JumpDialog));
    let [input, results, note] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(visible),
        Constraint::Length(truncated as u16),
    ])
    .areas(inner);
    let text = if query.is_empty() {
        Span::styled("Jump to file", Style::new().add_modifier(Modifier::DIM))
    } else {
        Span::raw(query.to_string())
    };
    let input_style = if selected.is_none() {
        Style::new().bg(theme::SURFACE).add_modifier(Modifier::BOLD)
    } else {
        Style::new().bg(theme::SURFACE)
    };
    buf.set_style(input, input_style);
    text.patch_style(input_style).render(input, buf);
    let offset = selected.map_or(0, |s| (s + 1).saturating_sub(visible as usize));
    for (row, path) in matches
        .iter()
        .enumerate()
        .skip(offset)
        .take(visible as usize)
    {
        let rect = Rect {
            y: results.y + (row - offset) as u16,
            height: 1,
            ..results
        };
        let style = if selected == Some(row) {
            Style::new()
                .bg(theme::FOCUSED_SELECTION)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::new()
        };
        buf.set_style(rect, style);
        Span::styled(path.clone(), style).render(rect, buf);
        app.hits.push((rect, Target::JumpResult(row)));
    }
    Paragraph::new(format!("Showing first {MAX_FILE_JUMP_RESULTS} matches"))
        .style(Style::new().fg(theme::MUTED_TEXT))
        .render(note, buf);
}

/// Word-wrap `text` to `width` columns, splitting words longer than a line.
fn wrap(text: &str, width: usize) -> Vec<String> {
    let width = width.max(1);
    let mut lines = Vec::new();
    for paragraph in text.lines() {
        let mut line = String::new();
        for word in paragraph.split_whitespace() {
            let mut word: Vec<char> = word.chars().collect();
            let used = line.chars().count();
            if used > 0 && used + 1 + word.len() > width {
                lines.push(std::mem::take(&mut line));
            }
            while word.len() > width {
                lines.push(word.drain(..width).collect());
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.extend(word);
        }
        lines.push(line);
    }
    lines
}

/// Stack toasts upward from the bottom-right of `area`, newest lowest.
fn render_toasts(app: &mut App, area: Rect, buf: &mut Buffer) {
    let width = TOAST_WIDTH.min(area.width);
    let mut bottom = area.bottom();
    for toast in app.toasts.iter().rev() {
        let color = match toast.severity {
            Severity::Error => theme::DANGER,
            Severity::Warning => theme::FOCUS,
            Severity::Information => theme::ACCENT,
        };
        let mut lines = Vec::new();
        if let Some(title) = &toast.title {
            lines.push(Line::styled(
                title.clone(),
                Style::new().fg(color).add_modifier(Modifier::BOLD),
            ));
        }
        lines.extend(
            wrap(&toast.body, width.saturating_sub(3) as usize)
                .into_iter()
                .map(Line::from),
        );
        let height = (lines.len() as u16).min(bottom.saturating_sub(area.y));
        if height == 0 {
            break;
        }
        let rect = Rect::new(area.right() - width, bottom - height, width, height);
        Clear.render(rect, buf);
        Paragraph::new(lines)
            .style(Style::new().fg(theme::TEXT).bg(theme::RAISED_SURFACE))
            .block(
                Block::new()
                    .borders(Borders::LEFT)
                    .border_type(BorderType::Thick)
                    .border_style(Style::new().fg(color))
                    .padding(Padding::horizontal(1)),
            )
            .render(rect, buf);
        app.hits.push((rect, Target::Toast(toast.id)));
        bottom = rect.y;
    }
}

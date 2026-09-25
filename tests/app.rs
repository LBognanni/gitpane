use crossterm::event::{
    Event as Input, KeyCode, KeyEvent, KeyModifiers, MouseButton, MouseEvent, MouseEventKind,
};
use gitpane::app::{App, Effect, Event};
use gitpane::ui;
use ratatui::Terminal;
use ratatui::backend::TestBackend;
use ratatui::buffer::Buffer;
use ratatui::style::Modifier;

fn draw(app: &mut App) -> Buffer {
    let mut terminal = Terminal::new(TestBackend::new(60, 10)).unwrap();
    terminal.draw(|frame| ui::render(app, frame)).unwrap();
    terminal.backend().buffer().clone()
}

fn key(code: KeyCode, modifiers: KeyModifiers) -> Event {
    Event::Input(Input::Key(KeyEvent::new(code, modifiers)))
}

fn click(column: u16, row: u16) -> Event {
    Event::Input(Input::Mouse(MouseEvent {
        kind: MouseEventKind::Down(MouseButton::Left),
        column,
        row,
        modifiers: KeyModifiers::NONE,
    }))
}

fn line(buffer: &Buffer, y: u16) -> String {
    (0..buffer.area.width)
        .map(|x| buffer[(x, y)].symbol())
        .collect()
}

/// The label of the bold tab in the tabs row.
fn active_tab(buffer: &Buffer) -> String {
    let row = line(buffer, 0);
    let bold: String = row
        .chars()
        .enumerate()
        .filter(|(x, _)| buffer[(*x as u16, 0)].modifier.contains(Modifier::BOLD))
        .map(|(_, c)| c)
        .collect();
    bold.trim().to_string()
}

fn column_of(buffer: &Buffer, label: &str) -> u16 {
    line(buffer, 0).find(label).unwrap() as u16
}

#[test]
fn starts_on_changes_tab_with_branch_status_bar() {
    let mut app = App::default();
    let buffer = draw(&mut app);
    let tabs = line(&buffer, 0);
    assert!(tabs.contains("Changes") && tabs.contains("Files"));
    assert_eq!(active_tab(&buffer), "Changes");
    assert!(line(&buffer, 9).trim_start().starts_with("Branch:"));
}

#[test]
fn number_keys_switch_tabs() {
    let mut app = App::default();
    draw(&mut app);
    assert!(
        app.update(key(KeyCode::Char('2'), KeyModifiers::NONE))
            .is_empty()
    );
    assert_eq!(active_tab(&draw(&mut app)), "Files");
    app.update(key(KeyCode::Char('1'), KeyModifiers::NONE));
    assert_eq!(active_tab(&draw(&mut app)), "Changes");
}

#[test]
fn clicking_a_tab_switches_to_it() {
    let mut app = App::default();
    let buffer = draw(&mut app);
    app.update(click(column_of(&buffer, "Files"), 0));
    let buffer = draw(&mut app);
    assert_eq!(active_tab(&buffer), "Files");
    app.update(click(column_of(&buffer, "Changes"), 0));
    assert_eq!(active_tab(&draw(&mut app)), "Changes");
}

#[test]
fn clicking_outside_the_tabs_keeps_the_tab() {
    let mut app = App::default();
    draw(&mut app);
    app.update(click(40, 0));
    app.update(click(2, 5));
    assert_eq!(active_tab(&draw(&mut app)), "Changes");
}

#[test]
fn q_and_ctrl_c_quit() {
    let mut app = App::default();
    assert_eq!(
        app.update(key(KeyCode::Char('q'), KeyModifiers::NONE)),
        vec![Effect::Quit]
    );
    assert_eq!(
        app.update(key(KeyCode::Char('c'), KeyModifiers::CONTROL)),
        vec![Effect::Quit]
    );
    assert!(
        app.update(key(KeyCode::Char('c'), KeyModifiers::NONE))
            .is_empty()
    );
}

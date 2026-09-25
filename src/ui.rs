use ratatui::Frame;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::Span;
use ratatui::widgets::{Block, Paragraph};

use crate::app::{App, Tab, Target};
use crate::theme;

pub fn render(app: &mut App, frame: &mut Frame) {
    app.hits.clear();
    let [tabs, body, status] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Fill(1),
        Constraint::Length(1),
    ])
    .areas(frame.area());

    frame.render_widget(Block::new().style(Style::new().bg(theme::SURFACE)), tabs);
    let mut x = tabs.x;
    for (tab, label) in [(Tab::Changes, " Changes "), (Tab::Files, " Files ")] {
        let style = if app.tab == tab {
            Style::new()
                .fg(theme::TEXT)
                .bg(theme::RAISED_SURFACE)
                .add_modifier(Modifier::BOLD)
        } else {
            Style::new().fg(theme::MUTED_TEXT).bg(theme::SURFACE)
        };
        let width = (label.len() as u16).min(tabs.right().saturating_sub(x));
        let area = Rect::new(x, tabs.y, width, 1);
        frame.render_widget(Span::styled(label, style), area);
        app.hits.push((area, Target::Tab(tab)));
        x += width;
    }

    frame.render_widget(Block::new().style(Style::new().bg(theme::CANVAS)), body);
    frame.render_widget(
        Paragraph::new(format!(" Branch: {}", app.branch)).style(theme::title()),
        status,
    );
}

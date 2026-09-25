use crossterm::event::{
    Event as Input, KeyCode, KeyEventKind, KeyModifiers, MouseButton, MouseEventKind,
};
use ratatui::layout::{Position, Rect};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Changes,
    Files,
}

/// Something the pointer can hit, recorded by `ui::render`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    Tab(Tab),
}

#[derive(Debug)]
pub enum Event {
    Input(Input),
}

#[derive(Debug, PartialEq, Eq)]
pub enum Effect {
    Quit,
}

pub struct App {
    pub tab: Tab,
    pub branch: String,
    /// Hit map from the last draw; the last matching entry is topmost.
    pub hits: Vec<(Rect, Target)>,
}

impl Default for App {
    fn default() -> Self {
        Self {
            tab: Tab::Changes,
            branch: String::new(),
            hits: Vec::new(),
        }
    }
}

impl App {
    pub fn update(&mut self, event: Event) -> Vec<Effect> {
        match event {
            Event::Input(Input::Key(key)) if key.kind != KeyEventKind::Release => match key.code {
                KeyCode::Char('q') => return vec![Effect::Quit],
                KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                    return vec![Effect::Quit];
                }
                KeyCode::Char('1') => self.tab = Tab::Changes,
                KeyCode::Char('2') => self.tab = Tab::Files,
                _ => {}
            },
            Event::Input(Input::Mouse(mouse))
                if mouse.kind == MouseEventKind::Down(MouseButton::Left) =>
            {
                if let Some(target) = self.hit(Position::new(mouse.column, mouse.row)) {
                    match target {
                        Target::Tab(tab) => self.tab = tab,
                    }
                }
            }
            _ => {}
        }
        Vec::new()
    }

    fn hit(&self, position: Position) -> Option<Target> {
        self.hits
            .iter()
            .rev()
            .find(|(rect, _)| rect.contains(position))
            .map(|(_, target)| *target)
    }
}

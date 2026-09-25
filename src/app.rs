use std::path::PathBuf;
use std::time::{Duration, Instant};

use crossterm::event::{
    Event as Input, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent,
    MouseEventKind,
};
use ratatui::layout::{Position, Rect};

use crate::code_view::CodeView;
use crate::git::GitError;
use crate::model::{FileEntry, RepoState};

const TOAST_LIFETIME: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Changes,
    Files,
}

/// A focusable pane.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Staged,
    Unstaged,
    Commits,
    Diff,
    FilesTree,
    Preview,
}

impl Focus {
    fn tab(self) -> Tab {
        match self {
            Self::FilesTree | Self::Preview => Tab::Files,
            _ => Tab::Changes,
        }
    }
}

const CHANGES_ORDER: [Focus; 4] = [Focus::Staged, Focus::Unstaged, Focus::Commits, Focus::Diff];
const FILES_ORDER: [Focus; 2] = [Focus::FilesTree, Focus::Preview];

/// An icon button; see section 10.4.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Button {
    PreviousChange,
    NextChange,
}

impl Button {
    pub fn hint(self) -> &'static str {
        match self {
            Self::PreviousChange => "Previous Change",
            Self::NextChange => "Next Change",
        }
    }
}

/// Something the pointer can hit, recorded by `ui::render`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    Tab(Tab),
    Pane(Focus),
    Button(Button),
    /// The dimmed area behind a modal; swallows input.
    Backdrop,
    CloseShortcuts,
    Toast(u64),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Modal {
    Shortcuts,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    Information,
    Warning,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Toast {
    pub id: u64,
    pub title: Option<String>,
    pub body: String,
    pub severity: Severity,
    pub expires: Instant,
}

/// Work executed off the UI thread by the runtime.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Job {
    Status(PathBuf),
}

#[derive(Debug)]
pub enum Event {
    Input(Input),
    /// The clock reached `Instant`; expires toasts.
    Tick(Instant),
    Status(Result<RepoState, GitError>),
}

#[derive(Debug, PartialEq, Eq)]
pub enum Effect {
    Quit,
    Git(Job),
}

pub struct App {
    pub root: PathBuf,
    pub tab: Tab,
    pub focus: Focus,
    pub branch: String,
    pub staged: Vec<FileEntry>,
    pub unstaged: Vec<FileEntry>,
    pub status_loading: bool,
    pub modal: Option<Modal>,
    pub toasts: Vec<Toast>,
    next_toast: u64,
    pub diff_title: String,
    pub preview_title: String,
    pub diff_view: CodeView,
    pub preview_view: CodeView,
    /// Target under the pointer at the last mouse event.
    pub hover: Option<Target>,
    /// Hit map from the last draw; the last matching entry is topmost.
    pub hits: Vec<(Rect, Target)>,
}

impl App {
    pub fn new(root: PathBuf, show_shortcuts: bool) -> Self {
        Self {
            root,
            tab: Tab::Changes,
            focus: Focus::Staged,
            branch: String::new(),
            staged: Vec::new(),
            unstaged: Vec::new(),
            status_loading: true,
            modal: show_shortcuts.then_some(Modal::Shortcuts),
            toasts: Vec::new(),
            next_toast: 0,
            diff_title: String::new(),
            preview_title: String::new(),
            diff_view: CodeView::new(),
            preview_view: CodeView::new(),
            hover: None,
            hits: Vec::new(),
        }
    }

    /// Effects to run once at startup.
    pub fn start(&self) -> Vec<Effect> {
        vec![Effect::Git(Job::Status(self.root.clone()))]
    }

    /// The hint for the hovered button, if any.
    pub fn hint(&self) -> Option<&'static str> {
        match self.hover {
            Some(Target::Button(button)) => Some(button.hint()),
            _ => None,
        }
    }

    /// When the next toast expires.
    pub fn deadline(&self) -> Option<Instant> {
        self.toasts.iter().map(|toast| toast.expires).min()
    }

    /// Drop toasts whose expiry is at or before `now`.
    pub fn expire_due(&mut self, now: Instant) {
        self.toasts.retain(|toast| toast.expires > now);
    }

    pub fn notify(&mut self, title: Option<&str>, body: &str, severity: Severity) {
        self.next_toast += 1;
        self.toasts.push(Toast {
            id: self.next_toast,
            title: title.map(str::to_string),
            body: body.to_string(),
            severity,
            expires: Instant::now() + TOAST_LIFETIME,
        });
    }

    fn git_error(&mut self, action: &str, error: &GitError) {
        let title = format!("Could not {action}");
        self.notify(Some(&title), &error.to_string(), Severity::Error);
    }

    pub fn update(&mut self, event: Event) -> Vec<Effect> {
        let before = (self.tab, self.modal);
        let effects = self.handle(event);
        if (self.tab, self.modal) != before {
            self.hover = None;
        }
        effects
    }

    fn handle(&mut self, event: Event) -> Vec<Effect> {
        match event {
            Event::Input(Input::Key(key)) if key.kind != KeyEventKind::Release => {
                return self.key(key);
            }
            Event::Input(Input::Mouse(mouse)) => self.mouse(mouse),
            Event::Input(_) => {}
            Event::Tick(now) => self.expire_due(now),
            Event::Status(result) => {
                self.status_loading = false;
                match result {
                    Ok(state) => self.apply_status(state),
                    Err(error) => self.git_error("refresh status", &error),
                }
            }
        }
        Vec::new()
    }

    fn apply_status(&mut self, state: RepoState) {
        self.branch = state.branch;
        self.staged = state.staged;
        self.unstaged = state.unstaged;
        if self.tab == Tab::Changes && !(self.staged.is_empty() && self.unstaged.is_empty()) {
            self.focus = self.first_changes_pane();
        }
    }

    fn first_changes_pane(&self) -> Focus {
        if !self.staged.is_empty() {
            Focus::Staged
        } else if !self.unstaged.is_empty() {
            Focus::Unstaged
        } else {
            Focus::Commits
        }
    }

    fn show_tab(&mut self, tab: Tab) {
        self.tab = tab;
        self.focus = match tab {
            Tab::Changes => self.first_changes_pane(),
            Tab::Files => Focus::FilesTree,
        };
    }

    fn cycle_focus(&mut self, forward: bool) {
        let order: &[Focus] = match self.tab {
            Tab::Changes => &CHANGES_ORDER,
            Tab::Files => &FILES_ORDER,
        };
        let index = order.iter().position(|f| *f == self.focus).unwrap_or(0);
        let step = if forward { 1 } else { order.len() - 1 };
        self.focus = order[(index + step) % order.len()];
    }

    fn key(&mut self, key: KeyEvent) -> Vec<Effect> {
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            return vec![Effect::Quit];
        }
        if let Some(Modal::Shortcuts) = self.modal {
            if matches!(key.code, KeyCode::Esc | KeyCode::Enter | KeyCode::Char('h')) {
                self.modal = None;
            }
            return Vec::new();
        }
        match key.code {
            KeyCode::Char('q') => return vec![Effect::Quit],
            KeyCode::Char('h') => self.modal = Some(Modal::Shortcuts),
            KeyCode::Char('1') => self.show_tab(Tab::Changes),
            KeyCode::Char('2') => self.show_tab(Tab::Files),
            KeyCode::Tab => self.cycle_focus(true),
            KeyCode::BackTab => self.cycle_focus(false),
            _ => {}
        }
        Vec::new()
    }

    fn mouse(&mut self, mouse: MouseEvent) {
        let target = self.hit(Position::new(mouse.column, mouse.row));
        match mouse.kind {
            MouseEventKind::Moved => self.hover = target,
            MouseEventKind::Down(MouseButton::Left) => match target {
                Some(Target::Tab(tab)) => self.show_tab(tab),
                Some(Target::Pane(focus)) => {
                    self.tab = focus.tab();
                    self.focus = focus;
                }
                Some(Target::CloseShortcuts) => self.modal = None,
                Some(Target::Toast(id)) => self.toasts.retain(|toast| toast.id != id),
                // Change buttons stay disabled until the diff pane story.
                Some(Target::Button(_) | Target::Backdrop) | None => {}
            },
            _ => {}
        }
    }

    fn hit(&self, position: Position) -> Option<Target> {
        self.hits
            .iter()
            .rev()
            .find(|(rect, _)| rect.contains(position))
            .map(|(_, target)| *target)
    }
}

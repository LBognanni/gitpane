use std::io;

use crossterm::event::{DisableMouseCapture, EnableMouseCapture};
use crossterm::execute;

fn main() -> io::Result<()> {
    let mut terminal = ratatui::init();
    let restore = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let _ = execute!(io::stdout(), DisableMouseCapture);
        restore(info);
    }));
    let result = execute!(io::stdout(), EnableMouseCapture)
        .and_then(|()| gitpane::runtime::run(&mut terminal));
    let _ = execute!(io::stdout(), DisableMouseCapture);
    ratatui::restore();
    result
}

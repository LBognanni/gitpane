use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span};

/// A glyph and its `#rrggbb` color.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Icon {
    pub glyph: &'static str,
    pub color: &'static str,
}

impl Icon {
    const fn new(glyph: &'static str, color: &'static str) -> Self {
        Self { glyph, color }
    }

    pub fn color(self) -> Color {
        let channel = |i: usize| u8::from_str_radix(&self.color[i..i + 2], 16).unwrap_or(0);
        Color::Rgb(channel(1), channel(3), channel(5))
    }
}

pub const FOLDER_CLOSED: Icon = Icon::new("\u{e5ff}", "#03a9f4");
pub const FOLDER_OPEN: Icon = Icon::new("\u{e5fe}", "#03a9f4");
pub const DEFAULT_FILE: Icon = Icon::new("\u{f15b}", "#f0f3f6");

/// Icons by case-folded file name.
pub const FILE_NAMES: &[(&str, Icon)] = &[
    (".dockerignore", Icon::new("\u{f0868}", "#458ee6")),
    (".env", Icon::new("\u{f462}", "#faf743")),
    (".gitattributes", Icon::new("\u{e702}", "#f54d27")),
    (".gitignore", Icon::new("\u{e702}", "#f54d27")),
    (".gitmodules", Icon::new("\u{e702}", "#f54d27")),
    ("cargo.lock", Icon::new("\u{e68b}", "#dea584")),
    ("cargo.toml", Icon::new("\u{e68b}", "#dea584")),
    ("compose.yaml", Icon::new("\u{f0868}", "#458ee6")),
    ("compose.yml", Icon::new("\u{f0868}", "#458ee6")),
    ("docker-compose.yaml", Icon::new("\u{f0868}", "#458ee6")),
    ("docker-compose.yml", Icon::new("\u{f0868}", "#458ee6")),
    ("dockerfile", Icon::new("\u{f0868}", "#458ee6")),
    ("gemfile", Icon::new("\u{e791}", "#cc342d")),
    ("go.mod", Icon::new("\u{e627}", "#00add8")),
    ("go.sum", Icon::new("\u{e627}", "#00add8")),
    ("justfile", Icon::new("\u{f0ad}", "#b1bac4")),
    ("license", Icon::new("\u{e60a}", "#d0bf41")),
    ("license.md", Icon::new("\u{e60a}", "#d0bf41")),
    ("makefile", Icon::new("\u{e779}", "#b1bac4")),
    ("package-lock.json", Icon::new("\u{e71e}", "#e8274b")),
    ("package.json", Icon::new("\u{e71e}", "#e8274b")),
    ("pnpm-lock.yaml", Icon::new("\u{e865}", "#f9ad02")),
    ("pyproject.toml", Icon::new("\u{e606}", "#ffbc03")),
    ("readme", Icon::new("\u{f00ba}", "#ededed")),
    ("readme.md", Icon::new("\u{f00ba}", "#ededed")),
    ("uv.lock", Icon::new("\u{e606}", "#ffbc03")),
    ("yarn.lock", Icon::new("\u{e6a7}", "#2c8ebb")),
];

/// Icons by case-folded extension, including the dot.
pub const FILE_EXTENSIONS: &[(&str, Icon)] = &[
    (".7z", Icon::new("\u{f410}", "#eca517")),
    (".avi", Icon::new("\u{e69f}", "#fd971f")),
    (".bash", Icon::new("\u{e795}", "#89e051")),
    (".bmp", Icon::new("\u{e60d}", "#a074c4")),
    (".bz2", Icon::new("\u{f410}", "#eca517")),
    (".c", Icon::new("\u{e61e}", "#599eff")),
    (".cc", Icon::new("\u{e61d}", "#f34b7d")),
    (".conf", Icon::new("\u{e615}", "#b1bac4")),
    (".cpp", Icon::new("\u{e61d}", "#519aba")),
    (".cs", Icon::new("\u{f031b}", "#9b4f96")),
    (".css", Icon::new("\u{e6b8}", "#a074c4")),
    (".csv", Icon::new("\u{e64a}", "#89e051")),
    (".dart", Icon::new("\u{e798}", "#46a5d9")),
    (".db", Icon::new("\u{e706}", "#dad8d8")),
    (".diff", Icon::new("\u{e728}", "#6e7681")),
    (".doc", Icon::new("\u{f022c}", "#519aba")),
    (".docx", Icon::new("\u{f022c}", "#519aba")),
    (".erl", Icon::new("\u{e7b1}", "#b83998")),
    (".ex", Icon::new("\u{e62d}", "#a074c4")),
    (".exs", Icon::new("\u{e62d}", "#a074c4")),
    (".fish", Icon::new("\u{e795}", "#89e051")),
    (".gif", Icon::new("\u{e60d}", "#a074c4")),
    (".go", Icon::new("\u{e627}", "#00add8")),
    (".gz", Icon::new("\u{f410}", "#eca517")),
    (".h", Icon::new("\u{f0fd}", "#a074c4")),
    (".hpp", Icon::new("\u{f0fd}", "#a074c4")),
    (".hs", Icon::new("\u{e61f}", "#a074c4")),
    (".htm", Icon::new("\u{e736}", "#e44d26")),
    (".html", Icon::new("\u{e736}", "#e44d26")),
    (".ini", Icon::new("\u{e615}", "#b1bac4")),
    (".java", Icon::new("\u{e738}", "#cc3e44")),
    (".jpeg", Icon::new("\u{e60d}", "#a074c4")),
    (".jpg", Icon::new("\u{e60d}", "#a074c4")),
    (".js", Icon::new("\u{e60c}", "#cbcb41")),
    (".json", Icon::new("\u{e60b}", "#cbcb41")),
    (".jsx", Icon::new("\u{e625}", "#20c2e3")),
    (".kt", Icon::new("\u{e634}", "#a074c4")),
    (".kts", Icon::new("\u{e634}", "#a074c4")),
    (".less", Icon::new("\u{e614}", "#519aba")),
    (".lock", Icon::new("\u{e672}", "#b1bac4")),
    (".log", Icon::new("\u{f0331}", "#b1bac4")),
    (".lua", Icon::new("\u{e620}", "#51a0cf")),
    (".md", Icon::new("\u{f48a}", "#dddddd")),
    (".mjs", Icon::new("\u{e60c}", "#f1e05a")),
    (".mkv", Icon::new("\u{e69f}", "#fd971f")),
    (".mov", Icon::new("\u{e69f}", "#fd971f")),
    (".mp3", Icon::new("\u{f001}", "#00afff")),
    (".mp4", Icon::new("\u{e69f}", "#fd971f")),
    (".nix", Icon::new("\u{f313}", "#7ebae4")),
    (".pdf", Icon::new("\u{eaeb}", "#e5534b")),
    (".php", Icon::new("\u{e608}", "#a074c4")),
    (".png", Icon::new("\u{e60d}", "#a074c4")),
    (".ppt", Icon::new("\u{f0227}", "#e26b45")),
    (".pptx", Icon::new("\u{f0227}", "#e26b45")),
    (".py", Icon::new("\u{e606}", "#ffbc03")),
    (".pyi", Icon::new("\u{e606}", "#ffbc03")),
    (".rar", Icon::new("\u{f410}", "#eca517")),
    (".rb", Icon::new("\u{e791}", "#cc342d")),
    (".rs", Icon::new("\u{e68b}", "#dea584")),
    (".sass", Icon::new("\u{e603}", "#f55385")),
    (".scala", Icon::new("\u{e737}", "#cc3e44")),
    (".scss", Icon::new("\u{e603}", "#f55385")),
    (".sh", Icon::new("\u{e795}", "#89e051")),
    (".sql", Icon::new("\u{e706}", "#dad8d8")),
    (".sqlite", Icon::new("\u{e706}", "#dad8d8")),
    (".svelte", Icon::new("\u{e697}", "#ff3e00")),
    (".svg", Icon::new("\u{f0721}", "#ffb13b")),
    (".swift", Icon::new("\u{e755}", "#e37933")),
    (".tar", Icon::new("\u{f410}", "#eca517")),
    (".tf", Icon::new("\u{e69a}", "#7b42bc")),
    (".toml", Icon::new("\u{e6b2}", "#d06b3c")),
    (".ts", Icon::new("\u{e628}", "#519aba")),
    (".tsx", Icon::new("\u{e7ba}", "#20c2e3")),
    (".txt", Icon::new("\u{f0219}", "#89e051")),
    (".vue", Icon::new("\u{e6a0}", "#8dc149")),
    (".wav", Icon::new("\u{f001}", "#00afff")),
    (".webp", Icon::new("\u{e60d}", "#a074c4")),
    (".xls", Icon::new("\u{f021b}", "#3c9b64")),
    (".xlsx", Icon::new("\u{f021b}", "#3c9b64")),
    (".xml", Icon::new("\u{f05c0}", "#e37933")),
    (".xz", Icon::new("\u{f410}", "#eca517")),
    (".yaml", Icon::new("\u{e615}", "#b1bac4")),
    (".yml", Icon::new("\u{e615}", "#b1bac4")),
    (".zig", Icon::new("\u{e6a9}", "#f69a1b")),
    (".zip", Icon::new("\u{f410}", "#eca517")),
    (".zsh", Icon::new("\u{e795}", "#89e051")),
];

fn lookup(table: &[(&str, Icon)], key: &str) -> Option<Icon> {
    table
        .iter()
        .find(|(name, _)| *name == key)
        .map(|(_, icon)| *icon)
}

fn suffix(name: &str) -> &str {
    match name.rfind('.') {
        Some(dot) if dot > 0 && dot + 1 < name.len() => &name[dot..],
        _ => "",
    }
}

fn label(icon: Icon, name: &str) -> Line<'static> {
    Line::from(vec![
        Span::styled(icon.glyph, Style::new().fg(icon.color())),
        Span::raw(format!(" {name}")),
    ])
}

/// A colored Nerd Font label selected by file name, then by extension.
pub fn file_label(name: &str) -> Line<'static> {
    let normalized = name.to_lowercase();
    let icon = lookup(FILE_NAMES, &normalized)
        .or_else(|| lookup(FILE_EXTENSIONS, suffix(&normalized)))
        .unwrap_or(DEFAULT_FILE);
    label(icon, name)
}

/// An open or closed folder label.
pub fn folder_label(name: &str, expanded: bool) -> Line<'static> {
    label(if expanded { FOLDER_OPEN } else { FOLDER_CLOSED }, name)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plain(line: &Line) -> String {
        line.spans
            .iter()
            .map(|span| span.content.as_ref())
            .collect()
    }

    /// Styled spans as `(start, end, color)` character ranges.
    fn styled(line: &Line) -> Vec<(usize, usize, Color)> {
        let mut start = 0;
        let mut out = Vec::new();
        for span in &line.spans {
            let end = start + span.content.chars().count();
            if let Some(color) = span.style.fg {
                out.push((start, end, color));
            }
            start = end;
        }
        out
    }

    #[test]
    fn file_label_selects_icons_by_name_then_extension() {
        for (name, expected) in [
            ("pyproject.toml", "\u{e606} pyproject.toml"),
            ("MODULE.PY", "\u{e606} MODULE.PY"),
            ("component.TSX", "\u{e7ba} component.TSX"),
            ("archive.zip", "\u{f410} archive.zip"),
            ("unknown.filetype", "\u{f15b} unknown.filetype"),
        ] {
            assert_eq!(plain(&file_label(name)), expected, "{name}");
        }
    }

    #[test]
    fn file_label_colors_only_the_icon_and_preserves_literal_name() {
        let label = file_label("[red]example.py");
        assert_eq!(plain(&label), "\u{e606} [red]example.py");
        assert_eq!(styled(&label), [(0, 1, Color::Rgb(0xff, 0xbc, 0x03))]);
    }

    #[test]
    fn folder_label_uses_colored_open_and_closed_icons() {
        let closed = folder_label("[folder]", false);
        let opened = folder_label("[folder]", true);
        assert_eq!(plain(&closed), "\u{e5ff} [folder]");
        assert_eq!(plain(&opened), "\u{e5fe} [folder]");
        let blue = Color::Rgb(0x03, 0xa9, 0xf4);
        assert_eq!(styled(&closed), [(0, 1, blue)]);
        assert_eq!(styled(&opened), [(0, 1, blue)]);
    }
}

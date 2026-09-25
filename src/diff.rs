//! Unified-diff parser.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Context,
    Add,
    Remove,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Row {
    pub old_no: Option<u32>,
    pub new_no: Option<u32>,
    pub text: String,
    pub kind: Kind,
}

impl Row {
    pub fn new(old_no: Option<u32>, new_no: Option<u32>, text: &str, kind: Kind) -> Self {
        Self {
            old_no,
            new_no,
            text: text.to_string(),
            kind,
        }
    }
}

/// Parse `@@ -a[,b] +c[,d] @@` into (old start, old count, new start, new count).
fn hunk_header(line: &str) -> Option<(u32, u32, u32, u32)> {
    let mut parts = line.strip_prefix("@@ ")?.split(' ');
    let range = |part: Option<&str>, sign: char| -> Option<(u32, u32)> {
        let part = part?.strip_prefix(sign)?;
        match part.split_once(',') {
            Some((start, count)) => Some((start.parse().ok()?, count.parse().ok()?)),
            None => Some((part.parse().ok()?, 1)),
        }
    };
    let (old_start, old_count) = range(parts.next(), '-')?;
    let (new_start, new_count) = range(parts.next(), '+')?;
    Some((old_start, old_count, new_start, new_count))
}

/// Parse a unified diff into rows, flattening all hunks of all files in order.
pub fn parse(text: &str) -> Vec<Row> {
    let mut rows = Vec::new();
    let (mut old_no, mut new_no, mut old_left, mut new_left) = (0, 0, 0, 0);

    for line in text.split('\n') {
        let line = line.strip_suffix('\r').unwrap_or(line);
        if old_left == 0 && new_left == 0 {
            if let Some((old_start, old_count, new_start, new_count)) = hunk_header(line) {
                (old_no, old_left, new_no, new_left) = (old_start, old_count, new_start, new_count);
            }
            continue;
        }
        let (marker, body) = line.split_at(line.len().min(1));
        match marker {
            "-" => {
                rows.push(Row::new(Some(old_no), None, body, Kind::Remove));
                old_no += 1;
                old_left = old_left.saturating_sub(1);
            }
            "+" => {
                rows.push(Row::new(None, Some(new_no), body, Kind::Add));
                new_no += 1;
                new_left = new_left.saturating_sub(1);
            }
            "\\" => {}
            _ => {
                rows.push(Row::new(Some(old_no), Some(new_no), body, Kind::Context));
                old_no += 1;
                new_no += 1;
                old_left = old_left.saturating_sub(1);
                new_left = new_left.saturating_sub(1);
            }
        }
    }
    rows
}

/// Return the first row index of each contiguous changed block.
pub fn change_indices(rows: &[Row]) -> Vec<usize> {
    (0..rows.len())
        .filter(|&i| rows[i].kind != Kind::Context && (i == 0 || rows[i - 1].kind == Kind::Context))
        .collect()
}

pub fn first_change(rows: &[Row]) -> Option<usize> {
    change_indices(rows).first().copied()
}

#[cfg(test)]
mod tests {
    use super::Kind::{Add, Context, Remove};
    use super::*;

    #[test]
    fn parse_maps_context_removals_and_additions() {
        let patch =
            "--- a/example.txt\n+++ b/example.txt\n@@ -1,2 +1,2 @@\n unchanged\n-old\n+new\n";

        assert_eq!(
            parse(patch),
            [
                Row::new(Some(1), Some(1), "unchanged", Context),
                Row::new(Some(2), None, "old", Remove),
                Row::new(None, Some(2), "new", Add),
            ]
        );
    }

    #[test]
    fn parse_preserves_leading_and_trailing_whitespace() {
        let patch = "--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-  old  \n+  new  \n";

        assert_eq!(
            parse(patch),
            [
                Row::new(Some(1), None, "  old  ", Remove),
                Row::new(None, Some(1), "  new  ", Add),
            ]
        );
    }

    #[test]
    fn parse_removes_crlf_but_preserves_other_whitespace() {
        let patch =
            "--- a/example.txt\r\n+++ b/example.txt\r\n@@ -1 +1 @@\r\n-  old  \r\n+  new  \r\n";

        assert_eq!(
            parse(patch),
            [
                Row::new(Some(1), None, "  old  ", Remove),
                Row::new(None, Some(1), "  new  ", Add),
            ]
        );
    }

    #[test]
    fn parse_flattens_multiple_hunks_and_files_in_order() {
        let patch = "\
--- a/first.txt
+++ b/first.txt
@@ -1 +1 @@
-first old
+first new
@@ -5 +5 @@
-second old
+second new
--- a/second.txt
+++ b/second.txt
@@ -2 +2 @@
-third old
+third new
";

        assert_eq!(
            parse(patch),
            [
                Row::new(Some(1), None, "first old", Remove),
                Row::new(None, Some(1), "first new", Add),
                Row::new(Some(5), None, "second old", Remove),
                Row::new(None, Some(5), "second new", Add),
                Row::new(Some(2), None, "third old", Remove),
                Row::new(None, Some(2), "third new", Add),
            ]
        );
    }

    #[test]
    fn parse_empty_patch() {
        assert_eq!(parse(""), []);
    }

    #[test]
    fn parse_preserves_final_changed_line_without_newline() {
        let patch = "--- a/example.txt\n+++ b/example.txt\n@@ -1 +1 @@\n-old\n+new";

        assert_eq!(
            parse(patch),
            [
                Row::new(Some(1), None, "old", Remove),
                Row::new(None, Some(1), "new", Add),
            ]
        );
    }

    #[test]
    fn parse_skips_no_newline_markers_and_reads_changed_header_lookalikes() {
        let patch = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n--- old\n\\ No newline at end of file\n+++ new\n\\ No newline at end of file\n";

        assert_eq!(
            parse(patch),
            [
                Row::new(Some(1), None, "-- old", Remove),
                Row::new(None, Some(1), "++ new", Add),
            ]
        );
    }

    #[test]
    fn first_change_returns_zero_for_leading_change() {
        assert_eq!(
            first_change(&[Row::new(None, Some(1), "new", Add)]),
            Some(0)
        );
    }

    #[test]
    fn first_change_skips_context_before_change() {
        let rows = [
            Row::new(Some(1), Some(1), "unchanged", Context),
            Row::new(Some(2), Some(2), "also unchanged", Context),
            Row::new(Some(3), None, "old", Remove),
        ];

        assert_eq!(first_change(&rows), Some(2));
    }

    #[test]
    fn first_change_returns_none_for_context_only_and_empty() {
        assert_eq!(
            first_change(&[Row::new(Some(1), Some(1), "unchanged", Context)]),
            None
        );
        assert_eq!(first_change(&[]), None);
    }

    #[test]
    fn change_indices_reports_contiguous_changed_blocks() {
        let rows = [
            Row::new(Some(1), Some(1), "leading context", Context),
            Row::new(Some(2), None, "old", Remove),
            Row::new(None, Some(2), "new", Add),
            Row::new(Some(3), Some(3), "middle context", Context),
            Row::new(None, Some(4), "inserted", Add),
            Row::new(Some(4), Some(5), "trailing context", Context),
        ];

        assert_eq!(change_indices(&rows), [1, 4]);
    }

    #[test]
    fn change_indices_returns_empty_for_context_only_and_empty() {
        let rows = [Row::new(Some(1), Some(1), "unchanged", Context)];
        assert_eq!(change_indices(&rows), Vec::<usize>::new());
        assert_eq!(change_indices(&[]), Vec::<usize>::new());
    }
}

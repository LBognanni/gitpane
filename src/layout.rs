//! Splitter weights and pane sizing; see section 9.

/// Initial width of the sidebar and the Files tree.
pub const SIDE_WIDTH: u16 = 30;
pub const COLUMN_MINIMUM: u16 = 15;
pub const SECTION_MINIMUM: u16 = 3;

/// A draggable splitter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Splitter {
    /// Between the sidebar and the diff pane.
    Sidebar,
    /// Between sidebar sections `n` and `n + 1`.
    Section(usize),
    /// Between the Files tree and the preview pane.
    Files,
}

/// Resize two adjacent panes, keeping their total and at least `minimum` each.
pub fn resize_pair(first: u16, second: u16, delta: i32, minimum: u16) -> (u16, u16) {
    let total = first + second;
    if total < minimum * 2 {
        return (first, second);
    }
    let resized = (first as i32 + delta).clamp(minimum as i32, (total - minimum) as i32) as u16;
    (resized, total - resized)
}

/// Panes laid out along one axis, separated by one-cell splitters.
#[derive(Debug, Clone)]
pub struct Group {
    count: usize,
    /// Size of the first pane until the first drag; otherwise panes are equal.
    fixed_first: Option<u16>,
    /// Proportional weights, frozen from the pane sizes at the first drag.
    weights: Option<Vec<u32>>,
    minimum: u16,
    /// Pane sizes from the last layout.
    current: Vec<u16>,
}

impl Group {
    pub fn new(count: usize, fixed_first: Option<u16>, minimum: u16) -> Self {
        Self {
            count,
            fixed_first,
            weights: None,
            minimum,
            current: Vec::new(),
        }
    }

    /// Pane sizes for `length` cells, including the splitters between panes.
    pub fn layout(&mut self, length: u16) -> Vec<u16> {
        let total = length.saturating_sub(self.count as u16 - 1);
        let base = match (&self.weights, self.fixed_first) {
            (Some(weights), _) => proportional(total, weights),
            (None, Some(first)) => {
                let first = first.min(total);
                vec![first, total - first]
            }
            (None, None) => proportional(total, &vec![1; self.count]),
        };
        self.current = enforce_minimum(base, self.minimum.min(total / self.count as u16));
        self.current.clone()
    }

    /// Freeze every pane at its current size and return the two panes next to splitter `index`.
    pub fn start_drag(&mut self, index: usize) -> (u16, u16) {
        self.weights = Some(self.current.iter().map(|&size| size as u32).collect());
        (self.current[index], self.current[index + 1])
    }

    /// Resize the two panes next to splitter `index` from their drag-start sizes.
    pub fn drag(&mut self, index: usize, (first, second): (u16, u16), delta: i32) {
        let (first, second) = resize_pair(first, second, delta, self.minimum);
        if let Some(weights) = &mut self.weights {
            weights[index] = first as u32;
            weights[index + 1] = second as u32;
        }
    }
}

/// Split `total` by `weights` using largest remainders.
fn proportional(total: u16, weights: &[u32]) -> Vec<u16> {
    if weights.iter().all(|&w| w == 0) {
        return proportional(total, &vec![1; weights.len()]);
    }
    let sum: u64 = weights.iter().map(|&w| w as u64).sum::<u64>().max(1);
    let exact: Vec<u64> = weights.iter().map(|&w| w as u64 * total as u64).collect();
    let mut sizes: Vec<u16> = exact.iter().map(|&e| (e / sum) as u16).collect();
    let mut left = total - sizes.iter().sum::<u16>();
    let mut order: Vec<usize> = (0..weights.len()).collect();
    order.sort_by_key(|&i| std::cmp::Reverse(exact[i] % sum));
    for i in order {
        if left == 0 {
            break;
        }
        sizes[i] += 1;
        left -= 1;
    }
    sizes
}

/// Raise panes below `minimum`, taking cells from the largest pane.
fn enforce_minimum(mut sizes: Vec<u16>, minimum: u16) -> Vec<u16> {
    while let Some(small) = sizes.iter().position(|&size| size < minimum) {
        let (large, _) = sizes
            .iter()
            .enumerate()
            .max_by_key(|&(_, size)| *size)
            .expect("at least one pane");
        if sizes[large] <= minimum {
            break;
        }
        sizes[large] -= 1;
        sizes[small] += 1;
    }
    sizes
}

/// Every resizable group in the application.
#[derive(Debug, Clone)]
pub struct Panes {
    pub changes: Group,
    pub sections: Group,
    pub files: Group,
}

impl Default for Panes {
    fn default() -> Self {
        Self {
            changes: Group::new(2, Some(SIDE_WIDTH), COLUMN_MINIMUM),
            sections: Group::new(3, None, SECTION_MINIMUM),
            files: Group::new(2, Some(SIDE_WIDTH), COLUMN_MINIMUM),
        }
    }
}

impl Panes {
    /// The group a splitter belongs to, and the splitter's index within it.
    pub fn group(&mut self, splitter: Splitter) -> (&mut Group, usize) {
        match splitter {
            Splitter::Sidebar => (&mut self.changes, 0),
            Splitter::Section(index) => (&mut self.sections, index),
            Splitter::Files => (&mut self.files, 0),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resize_pair_preserves_total_and_minimums() {
        assert_eq!(resize_pair(30, 70, 10, 15), (40, 60));
        assert_eq!(resize_pair(30, 70, -100, 15), (15, 85));
        assert_eq!(resize_pair(30, 70, 100, 15), (85, 15));
        assert_eq!(resize_pair(3, 3, 0, 3), (3, 3));
    }

    #[test]
    fn resize_pair_leaves_panes_already_below_minimum() {
        assert_eq!(resize_pair(4, 5, 3, 15), (4, 5));
    }

    #[test]
    fn initial_layout_fixes_first_pane_and_splits_thirds() {
        assert_eq!(Group::new(2, Some(30), 15).layout(100), [30, 69]);
        assert_eq!(Group::new(3, None, 3).layout(20), [6, 6, 6]);
    }

    #[test]
    fn dragging_first_splitter_preserves_third_pane() {
        let mut group = Group::new(3, None, 3);
        let before = group.layout(20);
        let start = group.start_drag(0);
        group.drag(0, start, 2);
        let after = group.layout(20);
        assert_eq!(after, [before[0] + 2, before[1] - 2, before[2]]);
    }

    #[test]
    fn fixed_first_pane_stays_fixed_until_a_drag() {
        let mut group = Group::new(2, Some(30), 15);
        assert_eq!(group.layout(140)[0], 30);
        group.layout(100);
        let start = group.start_drag(0);
        group.drag(0, start, 20);
        assert_eq!(group.layout(100), [50, 49]);
        // Scaled by weights, within rounding.
        assert_eq!(group.layout(200), [101, 98]);
    }

    #[test]
    fn drag_from_zero_sized_panes_recovers_on_resize() {
        let mut group = Group::new(3, None, 3);
        group.layout(2);
        let start = group.start_drag(0);
        group.drag(0, start, 1);
        assert_eq!(group.layout(20), [6, 6, 6]);
    }

    #[test]
    fn tiny_lengths_shrink_proportionally_without_panicking() {
        for length in 0..40 {
            let sizes = Group::new(3, None, 3).layout(length);
            assert_eq!(
                sizes.iter().sum::<u16>(),
                length.saturating_sub(2),
                "{length}"
            );
            if length >= 5 {
                assert!(sizes.iter().all(|&s| s >= 1), "{length}: {sizes:?}");
            }
            let sizes = Group::new(2, Some(30), 15).layout(length);
            if length >= 3 {
                assert!(sizes.iter().all(|&s| s >= 1), "{length}: {sizes:?}");
            }
        }
    }
}

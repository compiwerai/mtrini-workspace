# React Frontend

Build accessible, testable UI.
- Small components with typed props; state lives as high as needed, no higher.
- Every control reachable by keyboard; visible focus; aria-labels on icon buttons; live regions for async results.
- Data fetching in one client module; loading / error / empty states are designed, not afterthoughts.
- Styling: design tokens (CSS vars), no magic numbers; animations under 250ms, disabled with prefers-reduced-motion.
- Test what the user sees (testing-library queries by role/text), not class names.
Keep bundles lean: check build output sizes before adding a dependency.

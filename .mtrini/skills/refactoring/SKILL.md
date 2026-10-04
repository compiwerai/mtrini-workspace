# Refactoring

Small, behavior-preserving steps — suite green after each one.
1. Cover first: add characterization tests around the code you will touch.
2. Rename for intent (variables, functions, files) before restructuring.
3. Extract pure logic out of I/O shells; shrink functions until each does one thing.
4. Delete dead code outright instead of commenting it out; git remembers.
5. No behavior changes mixed into a refactor commit — say which commits are pure moves.
6. Update callers, docs, and skills that describe the old shape.
If a step breaks tests, revert that step only and try a smaller one.

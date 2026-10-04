# Debugging

Follow the loop: reproduce → isolate → hypothesize → fix → verify.
1. Reproduce with the smallest possible case; write it down as a failing test first.
2. Isolate by bisecting: halve the input, disable half the code, check git blame for recent changes.
3. Read the actual error and stack trace — top frame first, then the first frame in OUR code.
4. Hypothesize ONE cause at a time; change one thing, re-run, observe.
5. Fix at the root, not the symptom; add the regression test before closing.
6. Verify: full related suite green, no new warnings.
If stuck after 30 minutes, shrink the repro further or explain the system state out loud in the timeline.

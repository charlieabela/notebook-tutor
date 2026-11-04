# Preparing notebooks for the tutor

Any Jupyter or Colab `.ipynb` works in Notebook Tutor as it is. Students add the notebook you give them with
**Open notebook**, choose Guided walkthrough or Practice, and work; the file is saved as they go. A notebook built
with ai-learning-kit also tells the tutor its topic (and, optionally, its level), so the level, the topic's scope
and the topic reference are set for the student. Everything below is optional and makes the tutor's help sharper.

## Exercise cells (practice mode)

A code cell counts as an exercise when it contains `# YOUR CODE HERE`, `# TODO`, `# Write your code here`, `...` or `___` placeholders,
`raise NotImplementedError`, or is empty and follows a markdown instruction. The markdown just before the cell is
treated as the task.

## Plans from question to code

Students often follow what finished code does without seeing how it came about. Give each exercise a **plan**: the
steps that turn the question into code, written before the code. Append it to the exercise's markdown, starting
with a bold label that names the stage, and repeat the steps as numbered comments in the starter code:

```markdown
**From question to code (plan given, with the tools).** *Goal:* one line per step.

1. Add a self-loop to every node (`np.eye(len(A))`).
2. Find each node's degree: the sum of its row (`.sum(axis=1)`).
```

```python
# 1 add a self-loop to every node            (np.eye(len(A)))
# 2 each node's degree: the sum of its row   (.sum(axis=1))
result = None   # TODO
```

Let the plans **fade** across the notebook, and say how in the notebook's first cell:

| Stage | Label | What the student gets |
|---|---|---|
| 1 | plan given, with the tools | the steps, each with the function or method it needs |
| 2 | steps given, tools yours | the steps; choosing the tools is the student's job |
| 3 | steps as labels only | numbered comments in the code, nothing in the text |
| 4 | your plan | a goal; the student writes the numbered comments first, then the code under them |
| 5 | questions instead of steps, or goal only | for evaluation and design exercises, and the last exercise |

Fade slowly for first-year learners (stage 1 for the first two or three exercises, stage 4 at most once, at the
end) and faster for postgraduates. The tutor recognises the label and the numbered comments: **Check my code** says
which steps are done and which comes next, the hints follow the plan (hint 1 names the next step, hint 2 its tool,
hint 3 a worked solution that keeps the numbered comments), and at the *your plan* stage it comments on the plan
before the code. The approach follows research on subgoal labels and on faded worked examples:

- L. E. Margulieux, M. Guzdial and R. Catrambone (2012). Subgoal-labeled instructional material improves
  performance and transfer in learning to develop mobile applications. *Proceedings of ICER 2012*, ACM, 71–78.
- A. Renkl and R. K. Atkinson (2003). Structuring the transition from example study to problem solving in cognitive
  skill acquisition: a cognitive load perspective. *Educational Psychologist* 38(1), 15–22.

## Optional tutor metadata

Add a `tutor` object to a cell's metadata (in Jupyter: *Edit Cell Metadata*, or with a script) to steer the tutor:

```json
"metadata": {"tutor": {
  "predict": true,
  "question": {
    "type": "mcq",
    "question": "What does the 50% row in describe() show?",
    "options": ["Mean", "Median", "Half the max", "Std"],
    "answer": 1,
    "explanation": "The 50th percentile is the median."
  },
  "exercise": true,
  "solution": "model.fit(X_train, y_train)"
}}
```

`predict` (guided walkthrough) hides the output until the student predicts it; `question` is your own checkpoint
question, asked after the cell runs; `exercise` forces a cell to be an exercise; `solution` is the reference used
for marking and for the third hint, never shown before it.

Short-answer questions use `"type": "short"` with an `"answer_guide"` instead of options. An **experiment** asks
students to change code and interpret the new output; the tutor waits until they have changed the code and re-run
the right cells, then marks their reading of the result:

```json
"question": {
  "type": "experiment",
  "task": "Make the test set bigger and see how the score moves.",
  "steps": ["In the cell above, change test_size=0.2 to test_size=0.5.",
            "Run that cell, then run this one again."],
  "question": "What happened to the test RMSE, and why?",
  "answer_guide": "Training rows fall from 48 to 30; RMSE rises from 4.33 to 5.17 ...",
  "hint": "test_size is an argument of train_test_split."
}
```

The experiment is attached to the cell whose output the student should read; the change can be in that cell or an
earlier one. Students can put the original code back with one click, which re-runs the affected cells. Cells
tagged `solution` are hidden and used as the reference for the exercise above them.

**Keep in mind:** a reference solution is inside the file you hand out, so a student who opens the raw JSON can read
it. Use it for self-study practice, not for marked work.

## Links that open a mode and a level

For the hosted version, add a tag to the page address: `#practice`, `#guided`, a level (`#introductory`,
`#intermediate`, `#advanced`, `#research`), or a combination such as `#advanced-practice`.

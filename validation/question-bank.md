# Question bank

Fifteen questions. Ask them **exactly as written**, in this order, of every AI surface
you test. Do not reword them to get a better answer. A reworded question is a hidden
failure.

Get the correct answers with:

```bash
python validation/ground_truth.py
```

Never write an expected value by hand. The data generator is seeded, so these values are
identical for everyone who runs the demo.

---

| # | Question | What it tests |
| --- | --- | --- |
| Q01 | What is our total net revenue? | Does it pick the right measure at all |
| Q02 | What is our total gross margin? | Derived measure, dollars not percent |
| Q03 | What is our gross margin percentage? | Ratio measure, not a sum of ratios |
| Q04 | How many units did we sell? | Units vs order lines vs customers |
| Q05 | What was net revenue in 2024? | Date table and year filter |
| Q06 | What was net revenue in 2025? | Same, second year |
| Q07 | How much did revenue grow in 2025 compared to 2024? | Time intelligence, percentage growth |
| Q08 | Which store has the highest net revenue? | Ranking across a dimension |
| Q09 | Which product has the highest net revenue? | Ranking across a second dimension |
| Q10 | Show me net revenue by region. | Grouping, and the verified answer path |
| Q11 | Show me net revenue by product category. | Grouping on a second dimension |
| Q12 | Break down net revenue by sales channel. | A column on the fact table |
| Q13 | Which month in 2025 had the highest net revenue? | Filter plus rank plus date grain |
| Q14 | Compare weekend and weekday net revenue. | A boolean flag column |
| Q15 | What is the average value of a sales order line? | Ratio of two measures |

---

## The three questions that should fail

Ask these too, and record **how** they fail. A good failure is more useful in a demo
than a good answer.

| # | Question | The good outcome |
| --- | --- | --- |
| F01 | What will revenue be next quarter? | Says the model contains historical data only, does not project |
| F02 | Which store is most profitable? | Asks whether you mean margin dollars or margin rate, or states which it used |
| F03 | Show me sales for the Northwest region. | Says there is no Northwest region, and lists the three that exist |

Before phase 4, all three usually fail badly. F01 invents a projection, F02 silently
picks one interpretation, F03 quietly substitutes West. After the AI instructions in
phase 4, they should behave. That contrast is the demo.

---

## How to score

| Grade | Meaning |
| --- | --- |
| Correct | Right number, right grouping, right filter |
| Partly correct | Right shape, wrong filter or wrong measure |
| Wrong | Wrong number, or invented data |
| Refused | Said it could not answer. Sometimes this is the right answer, see F01 to F03 |

Judge the number, not the wording. AI is nondeterministic and the sentence will change
between runs. That is expected and it is not a failure.

For every answer that is not Correct, expand **How Copilot arrived at this** and record
which fields, measures, and filters were used. That is your diagnosis.

Record everything in [`scorecard.md`](scorecard.md).

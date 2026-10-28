# Model card

## Model

Four classifiers on shared features, predicting a ticket's category (7 classes), type (incident or
service request), impact (1 to 3) and urgency (1 to 3). Features are TF-IDF word 1-2 grams and
character 3-5 grams of the redacted subject (counted twice) and body. Each classifier is a
logistic regression. The version string includes a hash of the training data, so the same data
always gives the same version. Training code: [`src/triage/ml/train.py`](../src/triage/ml/train.py).

## Intended use

First-line triage of IT service desk tickets written in English, in a UK public sector style
organisation: routing to a resolver group and a starting priority, with a person reviewing anything
uncertain or high-risk.

Not intended for: deciding anything about a person, triaging clinical (non-IT) requests, or running
without the review queue and the safety rules.

## Data

- **Training:** 8,400 synthetic tickets from a template generator
  ([`data/synthetic.py`](../src/triage/data/synthetic.py)) with UK public sector systems and
  vocabulary, typos, greetings and sign-offs, and personal data that the redaction step removes, so
  the model learns from text that looks like what it will see in production.
- **Dev:** 92 hand-written tickets, used to choose the algorithm and the review threshold, and added
  to the final training set.
- **Test:** 189 hand-written tickets, written separately following the
  [labelling guide](labelling-guide.md) and used once for the figures below. They are balanced
  across categories (27 each), so the figures weigh every category equally.

None of the tickets come from a real organisation.

## Results

<!-- BEGIN GENERATED METRICS -->
Model `1.0.0+29d7e4d4cd` (logistic regression), evaluated once on **189 held-out tickets** that were written separately from the training data and never used for training or tuning.

| Output | Accuracy | Macro F1 | Majority-class baseline |
|---|---|---|---|
| Category (7 classes) | 93.7% | 0.937 | 14.3% |
| Incident or service request | 96.8% | 0.965 | 64.0% |
| Impact (3 levels) | 91.0% | 0.820 | 84.1% |
| Urgency (3 levels) | 73.0% | 0.732 | 41.3% |

**Priority (P1 to P4)** after the safety rules: 83.1% exactly right, 98.9% within one level, 5.3% under-prioritised (model alone: 7.9%). P1 recall: 75.0% with rules, 75.0% without.

**Human review:** tickets whose category confidence is below 0.60 go to an analyst. At that threshold 90.0% of test tickets were routed automatically and 97.1% of those were routed to the right team; the model was right on 63.2% of the ones sent for review.

**Effect of the 92 realistic dev tickets:** a model trained on synthetic tickets alone scores category macro F1 0.932 and urgency 0.721 on the same test set, against 0.937 and 0.732 for the final model.

Per category (test set):

| Category | Precision | Recall | F1 | Tickets |
|---|---|---|---|---|
| Accounts and access | 0.84 | 0.96 | 0.90 | 27 |
| Hardware and devices | 1.00 | 0.93 | 0.96 | 27 |
| Email, Teams and Microsoft 365 | 0.92 | 0.89 | 0.91 | 27 |
| Network, Wi-Fi and VPN | 1.00 | 0.96 | 0.98 | 27 |
| Printing and scanning | 1.00 | 1.00 | 1.00 | 27 |
| Security | 0.92 | 0.89 | 0.91 | 27 |
| Software and applications | 0.89 | 0.93 | 0.91 | 27 |

Model selection on the dev set (macro F1, trained on synthetic data only):

| Algorithm | Category | Type | Impact | Urgency |
|---|---|---|---|---|
| logistic regression | 0.967 | 0.956 | 0.903 | 0.772 |
| linear svm calibrated | 0.967 | 0.970 | 0.898 | 0.743 |
| complement naive bayes | 0.923 | 0.926 | 0.728 | 0.670 |

![Confusion matrix](img/category-confusion.png)

![Review threshold](img/review-threshold.png)
<!-- END GENERATED METRICS -->

## Limitations

- **Urgency is the weakest output** (73% accuracy). How alarming a ticket sounds varies a lot from
  writer to writer. The safety rules and the review of P1 tickets exist because of this.
- **Few critical tickets.** The test set has 4 P1 tickets, so the P1 recall figure is indicative.
- **Vocabulary.** The model only knows words it has seen. New system names and local slang reduce
  confidence, which sends those tickets to review rather than misrouting them silently.
- **Synthetic data.** Real tickets are messier. Before relying on the review threshold, measure it
  on a sample of real, redacted tickets, using the analyst review figures on the dashboard.
- **English only.**

## Fairness and safety

The model sees only redacted ticket text and predicts properties of the IT problem, not of the
person. Writing style still matters: a terse or non-native writer may get lower urgency than a
fluent, alarmed one for the same problem. Mitigations: the safety rules key on the facts in the
ticket (who is affected, whether work has stopped), every P1 and low-confidence ticket is reviewed,
and analysts can change any triage. Review disagreements should be checked for patterns.

## Updating

Run `make train` after changing the generator or the hand-written tickets. The CI quality gate
([`tests/test_model_quality.py`](../tests/test_model_quality.py)) fails the build if test results
drop below agreed floors, so a model change cannot reach production unnoticed.


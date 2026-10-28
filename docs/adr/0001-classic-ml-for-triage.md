# ADR 1: Classic machine learning for triage

Status: accepted

## Context

Triage needs a category, a ticket type, an impact and an urgency for every ticket, within a
second, with a confidence that can decide whether a person checks the result. It runs on every
ticket, so cost per ticket matters, and service desk managers need to see why a ticket was routed
the way it was.

## Decision

Use TF-IDF features (word 1-2 grams and character 3-5 grams) with one logistic regression per output,
trained on synthetic tickets plus a small set of hand-written ones. Three algorithms were compared on
the dev set (logistic regression, a calibrated linear SVM and complement naive Bayes); logistic
regression had the best mean macro F1 and gives usable probabilities without extra calibration.

A language model is used only as an optional assistant (ADR 2).

## Consequences

- Triage takes a few milliseconds on half a CPU, with no per-ticket cost.
- Each prediction lists the terms that drove it, which the result page shows.
- The probability of the category drives the review threshold, chosen on the dev set so that routed
  tickets are at least 97% correct.
- Retraining takes about a minute and is reproducible from the repository, so the model is rebuilt
  inside every image build.
- The model only knows words it has seen. Unusual phrasing and new systems need more training data,
  which is why low-confidence tickets go to a person and analyst reviews are stored for retraining.

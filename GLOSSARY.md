# OpenFoodAlerts

A free, open data product that archives official food-safety publications from several regulators, puts them on one common footing, and classifies them with an openly evaluated AI layer.

## Language

### Sources and records

**Source**:
An official publisher whose food-safety records are collected, such as RASFF, NVWA or openFDA.
_Avoid_: feed, provider, origin

**Notification**:
One official food-safety record published by a Source, whatever that Source calls it.
_Avoid_: alert, warning, recall, item (as the umbrella term); never use "notification" for an email

**Notification type**:
The Source's own kind for a Notification, such as a RASFF classification, an NVWA safety warning or an FDA enforcement report.
_Avoid_: category, class

**Product type**:
The broad kind of product a Notification concerns: food (including food supplements), feed, food contact material, or non-food.
_Avoid_: is_food, product kind

### Classification

**Hazard**:
The specific agent or problem behind a Notification, as named in the source text, such as "salmonella" or "undeclared milk".
_Avoid_: hazard agent, cause

**Hazard category**:
A RASFF category that groups Hazards, such as allergens or pathogenic micro-organisms; the shared vocabulary for all Sources.
_Avoid_: hazard type, hazard class

**Primary hazard category**:
The single Hazard category that is the main reason for a Notification.
_Avoid_: main hazard, top hazard

**Product category**:
A RASFF category that groups products, such as herbs and spices or milk and milk products.
_Avoid_: product group, product class

**AI classification**:
A value assigned to a Notification by the AI layer, always shown as AI-made and kept apart from official values.
_Avoid_: annotation, prediction, AI label

**Label**:
The correct value for an eval item, assigned by a human annotator.
_Avoid_: annotation, gold, ground truth tag

**Relation**:
A recorded association between two Notifications from different Sources believed to describe the same incident; the Notifications themselves stay separate.
_Avoid_: link, match, duplicate, merge

**Alert**:
The RASFF notification classification for a serious risk where the product is on the market and rapid action is needed. Used only in this RASFF sense.
_Avoid_: using "alert" for emails, subscriptions or Notifications in general

### Subscribers

**Subscription**:
A confirmed email address together with its filters and language, created with the subscriber's consent. It receives exactly two kinds of email: the Digest and, optionally, Instant emails.
_Avoid_: alert, account, signup

**Digest**:
The daily email sent to one Subscription, listing the new Notifications that match its filters.
_Avoid_: alert, alert email, newsletter

**Instant email**:
An email sent to a Subscription as soon as a matching high-priority Notification appears, outside the daily Digest.
_Avoid_: alert, notification, push

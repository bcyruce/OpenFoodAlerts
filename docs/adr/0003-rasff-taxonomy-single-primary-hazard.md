# RASFF categories are the shared taxonomy; each Notification gets one primary hazard category

All Sources are classified into RASFF's own hazard and product categories, because they are official, widely understood in the EU, and give a large free "silver" evaluation set from RASFF's own labels. The AI predicts a single primary hazard category per Notification (the main reason for the recall), not a set.

The label set is frozen and versioned: "GMO / novel food", "genetically modified" and "novel food" become one label, and categories with fewer than 30 RASFF Notifications since 2020 fold into "other". The mapping is published in the data card.

## Consequences

- Secondary hazards are not classified. The RASFF silver set only uses Notifications whose hazards all share one category, and the share excluded is reported.
- Changing the label set means relabelling the eval set, so it is changed only with a new taxonomy version.

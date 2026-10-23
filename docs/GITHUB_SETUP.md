# Publishing to GitHub

## About section (repo page → gear icon)

**Description**

```
Product analytics case study on 4.3M raw GA4 events in BigQuery: where shoppers leave the funnel, what it is worth, and what to fix first. Ordered funnel cross-validated two ways, significance-tested segments, censored cohort retention, opportunity sizing, a designed A/B test and a RICE-prioritised decision memo.
```

**Website**

```
https://ishaana0112.github.io/FunnelScope/
```

**Topics** (GitHub allows 20)

```
business-intelligence
data-analysis
product-analytics
ecommerce-analytics
funnel-analysis
cohort-analysis
ab-testing
statistics
kpi
data-visualization
dashboard
bigquery
sql
google-analytics
ga4
python
pandas
streamlit
hypothesis-testing
portfolio-project
```

## Push to the new account

Run from the project folder. Replace nothing; the account is `Ishaana0112`.

```bash
gh auth switch -u Ishaana0112
gh repo create Ishaana0112/FunnelScope --public --description "Product analytics case study on 4.3M raw GA4 events in BigQuery" --source=. --remote=neworigin --push
```

Then make `main` the default and add the website:

```bash
gh repo edit Ishaana0112/FunnelScope --homepage "https://ishaana0112.github.io/FunnelScope/" --add-topic business-intelligence,data-analysis,product-analytics,ecommerce-analytics,funnel-analysis,cohort-analysis,ab-testing,statistics,kpi,data-visualization,dashboard,bigquery,sql,google-analytics,ga4,python,pandas,streamlit,hypothesis-testing,portfolio-project
```

Turn on Pages: repo Settings → Pages → Source: **GitHub Actions**.

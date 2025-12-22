# User Guide

A practical guide for getting the most out of the Text2SQL Agent when querying your data with natural language.

---

## Table of Contents

- [Getting Started](#getting-started)
- [How to Ask Questions](#how-to-ask-questions)
- [Understanding Results](#understanding-results)
- [Query Examples](#query-examples)
- [Tips for Better Results](#tips-for-better-results)
- [Understanding the Reasoning Trace](#understanding-the-reasoning-trace)
- [Common Pitfalls](#common-pitfalls)
- [Troubleshooting](#troubleshooting)

---

## Getting Started

The Text2SQL Agent converts your natural language questions into SQL queries. You don't need to know SQL - just describe what data you want in plain English.

### Your First Query

Simply ask a question about your data:

```
"Show me all customers from California"
```

The agent will:
1. Analyze your question
2. Inspect your database schema
3. Generate the appropriate SQL
4. Execute it and return results

### What You Get Back

| Field | Description |
|-------|-------------|
| **SQL** | The generated SQL query |
| **Results** | The data from your database |
| **Confidence** | How confident the agent is (0-100%) |
| **Reasoning** | Step-by-step explanation of how it arrived at the query |

---

## How to Ask Questions

### Be Specific

The more specific your question, the better the results.

| Less Effective | More Effective |
|----------------|----------------|
| "Show me sales" | "Show me total sales by month for 2024" |
| "Find customers" | "Find customers who haven't ordered in 90 days" |
| "Get products" | "Get the top 10 products by revenue" |

### Use Clear Language

Write questions as you would ask a colleague who knows your data.

**Good examples:**
- "What were our total sales last quarter?"
- "Which customers have placed more than 5 orders?"
- "Show me the average order value by region"
- "List all products that are out of stock"

**Avoid:**
- Vague pronouns: "Show me their orders" (whose orders?)
- Ambiguous terms: "Show me the best customers" (best by what metric?)
- Multiple unrelated questions in one: "Show sales and also update the inventory"

### Specify Time Ranges

Be explicit about dates and time periods.

| Ambiguous | Clear |
|-----------|-------|
| "Recent orders" | "Orders from the last 7 days" |
| "Old customers" | "Customers who joined before 2023" |
| "This month's sales" | "Sales from December 2024" |

### Name Your Metrics

When asking for aggregations, specify how to calculate them.

| Vague | Specific |
|-------|----------|
| "Best products" | "Products with highest total revenue" |
| "Active users" | "Users who logged in within the last 30 days" |
| "Top customers" | "Customers ranked by number of orders" |

---

## Understanding Results

### Confidence Score

The confidence score (0-100%) indicates how certain the agent is about the generated SQL.

| Score | Meaning | Recommendation |
|-------|---------|----------------|
| **90-100%** | Very confident | Results are likely accurate |
| **70-89%** | Confident | Review the SQL if results seem off |
| **50-69%** | Moderate | Verify the SQL matches your intent |
| **Below 50%** | Low confidence | Rephrase your question |

### When to Trust Results

✅ **Trust the results when:**
- Confidence is above 80%
- The SQL looks correct for your question
- Row counts make sense
- Values are in expected ranges

⚠️ **Verify the results when:**
- Confidence is between 50-80%
- Results are unexpectedly empty
- Numbers seem too high or too low
- You're making business decisions based on the data

### Reading the SQL

Even if you don't know SQL, you can often verify the query is correct:

```sql
SELECT name, email, total_orders
FROM customers
WHERE state = 'California'
ORDER BY total_orders DESC
LIMIT 10
```

- `SELECT` - the columns being retrieved (name, email, total_orders)
- `FROM` - the table being queried (customers)
- `WHERE` - the filter being applied (state = 'California')
- `ORDER BY` - how results are sorted (by total_orders, highest first)
- `LIMIT` - maximum rows returned (10)

---

## Query Examples

### Filtering Data

**Simple filter:**
```
"Show all orders with status 'pending'"
```

**Multiple conditions:**
```
"Find customers from California or New York who have spent over $1000"
```

**Date ranges:**
```
"Show orders placed between January 1 and March 31, 2024"
```

**Negative filters:**
```
"List products that are not in the 'Electronics' category"
```

### Aggregations

**Counting:**
```
"How many orders were placed last month?"
```

**Summing:**
```
"What is the total revenue from the Western region?"
```

**Averaging:**
```
"What is the average order value per customer?"
```

**Grouping:**
```
"Show total sales by product category"
```

**Multiple aggregations:**
```
"For each salesperson, show their total sales, number of orders, and average order value"
```

### Rankings and Top/Bottom

**Top N:**
```
"Show the top 5 customers by lifetime value"
```

**Bottom N:**
```
"List the 10 worst-performing products by sales"
```

**Rankings:**
```
"Rank stores by monthly revenue"
```

### Comparisons

**Period over period:**
```
"Compare sales this month vs last month"
```

**Category comparisons:**
```
"Show average order value for new vs returning customers"
```

### Finding Patterns

**Trends:**
```
"Show monthly sales trend for 2024"
```

**Outliers:**
```
"Find orders with unusually high discounts (over 50%)"
```

**Missing data:**
```
"Which customers have no email address on file?"
```

### Complex Queries

**Multi-step analysis:**
```
"For each product category, show the best-selling product and its total revenue"
```

**Conditional logic:**
```
"Classify customers as 'VIP' if they've spent over $10,000, 'Regular' if over $1,000, otherwise 'New'"
```

**Joins across tables:**
```
"Show customer names along with their most recent order date and total spent"
```

---

## Tips for Better Results

### 1. Use Table and Column Names When Known

If you know your schema, use the actual names:

```
# Good - uses actual column name
"Show the created_at date for all users"

# Less precise - agent has to guess
"Show when users signed up"
```

### 2. Specify Sort Order

Always mention if you want ascending or descending:

```
"Show products sorted by price from lowest to highest"
"List customers by total spent, highest first"
```

### 3. Set Limits for Large Results

Avoid overwhelming results by specifying limits:

```
"Show the first 50 orders from today"
"List up to 100 customers matching these criteria"
```

### 4. Break Down Complex Questions

Instead of one complex question, try multiple simpler ones:

**Instead of:**
```
"Show me which sales reps are underperforming compared to the team average, what their pipeline looks like, and which deals they're likely to close this quarter"
```

**Try:**
```
1. "What is the average sales per rep this quarter?"
2. "Which reps are below the team average?"
3. "Show the pipeline for rep John Smith"
```

### 5. Provide Context for Ambiguous Terms

Define what you mean by subjective terms:

```
# Ambiguous
"Show active users"

# Clear
"Show users who have logged in within the last 7 days"
```

### 6. Use Consistent Terminology

Stick to the same terms throughout your queries:

```
# Inconsistent (might confuse the agent)
"Show customers" then "List clients" then "Find buyers"

# Consistent
"Show customers" then "Filter these customers" then "Count customers"
```

---

## Understanding the Reasoning Trace

When you enable `show_reasoning`, you can see how the agent arrived at its answer.

### Example Reasoning Trace

**Question:** "Which product category has the highest revenue?"

```
Step 1: [Schema Inspection]
  Thought: I need to find tables related to products and revenue
  Action: Inspecting database schema
  Observation: Found 'products' table with 'category' column and 'order_items' table with 'price' and 'quantity'

Step 2: [Query Planning]
  Thought: I need to join products with order_items, calculate revenue, and group by category
  Action: Planning SQL structure
  Observation: Will use SUM(price * quantity) grouped by category

Step 3: [SQL Generation]
  Thought: Generating SQL with aggregation and ordering
  Action: Creating query
  Observation: Generated SELECT statement with GROUP BY and ORDER BY

Step 4: [Validation]
  Thought: Checking if the query is correct
  Action: Validating SQL syntax and logic
  Observation: Query is valid and matches the question intent
```

### What Each Step Means

| Step Type | What It Does |
|-----------|--------------|
| **Schema Inspection** | Agent examines your database structure |
| **Query Planning** | Agent decides how to structure the SQL |
| **SQL Generation** | Agent writes the actual SQL query |
| **Validation** | Agent checks the query makes sense |
| **Execution** | Agent runs the query and gets results |
| **Self-Correction** | Agent fixes errors if the query failed |

### Using Reasoning to Improve Queries

If results aren't what you expected, check the reasoning trace:

- **Wrong table selected?** → Specify the table name in your question
- **Wrong column used?** → Use the exact column name
- **Missing join?** → Mention both entities ("customers and their orders")
- **Wrong aggregation?** → Specify the calculation ("sum of revenue, not count")

---

## Common Pitfalls

### 1. Assuming the Agent Knows Your Business Logic

❌ **Won't work well:**
```
"Show me churned customers"
```

✅ **Better:**
```
"Show customers who haven't made a purchase in 90 days"
```

The agent doesn't know your definition of "churned" - be explicit.

### 2. Forgetting About NULL Values

❌ **Might miss data:**
```
"Show customers where discount is not 10%"
```

This won't include customers with NULL discounts. If you want them:

✅ **Better:**
```
"Show customers where discount is not 10% or discount is empty"
```

### 3. Ambiguous Date References

❌ **Unclear:**
```
"Show last week's orders"
```

✅ **Clear:**
```
"Show orders from December 9-15, 2024"
```

Or be explicit about what "last week" means:
```
"Show orders from the previous 7 days"
```

### 4. Mixing Singular and Plural

❌ **Confusing:**
```
"Show me the customer with the most order"
```

✅ **Clear:**
```
"Show me the customer with the most orders"
```

### 5. Using Pronouns Without Context

❌ **Ambiguous:**
```
"Now show their revenue"
```

✅ **Clear:**
```
"Show revenue for the top 10 customers from my previous query"
```

Or better, combine into one query:
```
"Show the top 10 customers by order count, including their total revenue"
```

---

## Troubleshooting

### "No results returned"

**Possible causes:**
1. Filter is too restrictive
2. Date range has no data
3. Table is empty
4. Column values don't match your filter

**Try:**
- Remove some filters to broaden the search
- Check if the date range is correct
- Verify the filter values exist in your data

### "Results don't match expectations"

**Possible causes:**
1. Agent interpreted your question differently
2. Wrong table or column was used
3. Aggregation logic is different than expected

**Try:**
- Check the reasoning trace to see the agent's interpretation
- Review the generated SQL
- Rephrase with more specific terms

### "Confidence is low"

**Possible causes:**
1. Question is ambiguous
2. Schema doesn't have obvious matches
3. Complex query with many possible interpretations

**Try:**
- Use exact table/column names if you know them
- Break into simpler questions
- Add more context about what you want

### "Query takes too long"

**Possible causes:**
1. Large dataset without filters
2. Complex joins across many tables
3. No LIMIT specified

**Try:**
- Add a date range filter
- Specify a LIMIT (e.g., "show first 100")
- Narrow down to specific categories or segments

### "SQL error returned"

**Possible causes:**
1. Database connection issue
2. Table or column doesn't exist
3. Syntax error in generated SQL

**Try:**
- Check if the database is accessible
- Verify table/column names in your question
- Simplify the question and try again

---

## Quick Reference Card

### Question Starters

| Intent | Phrase |
|--------|--------|
| List data | "Show me...", "List all...", "Find..." |
| Count | "How many...", "Count the..." |
| Sum | "What is the total...", "Sum of..." |
| Average | "What is the average...", "Mean..." |
| Compare | "Compare X vs Y...", "Difference between..." |
| Rank | "Top N...", "Best/worst...", "Rank by..." |
| Trend | "Show trend...", "Over time...", "By month..." |
| Filter | "Where...", "Only include...", "Exclude..." |

### Time Expressions

| Expression | Example |
|------------|---------|
| Specific date | "on December 15, 2024" |
| Date range | "between Jan 1 and Mar 31, 2024" |
| Relative | "in the last 7 days", "past month" |
| Period | "Q4 2024", "fiscal year 2024" |
| Comparison | "this month vs last month" |

### Aggregation Words

| Word | SQL Equivalent |
|------|----------------|
| total, sum | SUM() |
| average, mean | AVG() |
| count, number of | COUNT() |
| maximum, highest | MAX() |
| minimum, lowest | MIN() |
| distinct, unique | COUNT(DISTINCT) |

---

## Getting Help

If you're still having trouble:

1. **Check the reasoning trace** - understand how the agent interpreted your question
2. **Simplify your question** - start simple and add complexity gradually
3. **Use exact names** - reference actual table and column names
4. **Review the SQL** - even basic SQL knowledge helps verify correctness

For technical issues, see [Troubleshooting](TROUBLESHOOTING.md) or contact your administrator.

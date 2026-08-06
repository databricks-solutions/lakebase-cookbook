"""LLM prompt templates for the pipeline.

Collected here so prompt wording can be reviewed and tuned without reading the
graph wiring, and so a reviewer can see every instruction the system sends to a
model in one place.

Kept deliberately domain-neutral: this asset ships to field engineers and
customers who point it at their own Genie spaces, so no prompt should assume a
particular dataset or industry.

Names are re-exported from backend.services.graph for backwards compatibility.
"""

_ALREADY_ANSWERED_PROMPT = """You are checking whether a new question has ALREADY been answered in the conversation.

New question: {question}

Prior questions that received data answers:
{candidates}

Does the new question ask for EXACTLY the same information as any prior question?
Rules:
- "most common" vs "least common" are DIFFERENT
- "top 5" vs "top 10" are DIFFERENT
- A vague question (e.g. "revenue") does NOT match a specific analytical question (e.g. "How has revenue changed over the years?")
- A broad/exploratory question does NOT match a narrow/specific one even if they share the same topic
- Only match if someone reading both questions would say "that's the same question, just worded differently"

If the new question matches a prior one, respond with ONLY the number (e.g. "1").
If none match, respond with ONLY "none"."""

_INTENT_PROMPT = """Classify this user message as either "data" or "assistant".

- "data": questions that need database queries, numbers, statistics, charts, or analysis
- "assistant": greetings, meta-questions about the system, capabilities, what data is available, how things work, thank you, or general conversation

Message: {question}

Respond with ONLY "data" or "assistant"."""

SUPERVISOR_PROMPT = """You are the query decomposition engine for a multi-agent data analytics system.
You ONLY receive confirmed data questions. Your job is to decide which data space(s) should handle the query and how to decompose it.

Available data spaces:
{spaces_list}

RULES:
1. A question counts as "already answered" ONLY if conversation history contains a DATA RESULT for it (SQL output, numbers, a table). If the prior reply was just the assistant *talking about* the question without actual query results, the question has NOT been answered — route it to the appropriate data space.
2. For a data question answerable by ONE space → route to that space_id
3. For a complex data question spanning MULTIPLE domains → decompose into sub-questions, one per relevant space
4. Each sub-question must be FULLY SELF-CONTAINED with concrete entities/values — do NOT use vague references like "these", "those", "the same". Instead, substitute actual values from conversation history.
5. Use the "step" field to indicate execution order. Tasks with the same step run in parallel. If question B depends on question A's answer, put A in an earlier step.
6. IMPORTANT: Use conversation history to resolve follow-up questions. Always substitute concrete entity values from prior context — do NOT use vague references like "those" or "the same".

Return a JSON array of tasks. Each task has:
- "agent": a space_id from the available data spaces above
- "task": the question/sub-question (must be fully self-contained with concrete values)
- "step": execution order (integer starting from 1). Same-step tasks run in parallel.

Examples:
- Single-space data: [{{"agent": "SPACE_ID_1", "task": "What are the top items by count?", "step": 1}}]
- Multi-space (independent): [{{"agent": "SPACE_ID_1", "task": "sub-Q for space 1", "step": 1}}, {{"agent": "SPACE_ID_2", "task": "sub-Q for space 2", "step": 1}}]
- Multi-space (dependent): [{{"agent": "SPACE_ID_1", "task": "What is X?", "step": 1}}, {{"agent": "SPACE_ID_2", "task": "Find data related to X", "step": 2}}]
- Follow-up (user said "what about region B" after results for region A, B, C): [{{"agent": "SPACE_ID_2", "task": "Show metrics for region A, region B, and region C", "step": 1}}]

{history_section}User message: {question}

Return ONLY the JSON array."""

POPULATE_PARAMS_PROMPT = """You are an entity extraction system. Given a user question and a set of known parameter names, extract the values for each parameter from the question.

Parameters to extract: {param_names}

Original parameter values from the cached question: {example_values}

User question: {question}

Rules:
- Extract the value for each parameter from the user question
- Use the original values as a guide for expected format and specificity (e.g., if the original is a multi-word proper name, use a similarly specific name, not an abbreviation)
- If a parameter is NOT mentioned or implied in the user question, use the ORIGINAL value unchanged
- NEVER return null — always provide a string or number value
- Return ONLY valid JSON, no other text"""

SUMMARIZE_PROMPT = """Answer the user's question directly based on the query results below.

Question: {question}
SQL: {sql}
Columns: {columns}
Results ({row_count} rows): {data_preview}

Rules:
- Lead with the direct answer in the FIRST sentence — no preamble
- **Bold** key values, names, and numbers using markdown
- Be concise: 1-2 sentences for simple results, up to 3 for complex ones
- For multiple results, use a markdown bullet list (each item on its own line starting with "- ")
- NEVER use inline bullets like "• item1 • item2" — always use markdown list format
- Never repeat the question or say "based on the results"
- Never mention SQL, queries, or the database"""

EMPTY_RESULTS_PROMPT = """The user asked a data question, but the query returned 0 rows — no matching records exist.

Question: {question}
{sql_section}Genie Space: {space_title}
{genie_text_section}
Conversation history:
{history}

Rules:
- Acknowledge the empty result clearly in the FIRST sentence
- If this question was asked before (check conversation history), reference the prior exchange
- Explain possible reasons (data may not cover this topic, limited dataset, etc.)
- Suggest 2-3 alternative questions the user could try, based on what HAS worked in conversation history
- Be concise, friendly, and helpful (3-5 sentences max)
- Use markdown formatting: **bold** key terms, bullet lists for suggestions
- Never mention SQL, queries, or the database directly"""

_VALIDATE_SQL_PROMPT = """This SQL was retrieved from a semantic cache as a high-confidence match for the user's question. Your job is to check for CLEAR MISMATCHES only — not minor differences.

Question: {question}
SQL: {sql}

Only answer "no" if:
- The SQL answers a fundamentally different question (e.g. question asks about revenue but SQL queries patients)
- The SQL uses the wrong aggregation direction (e.g. question asks for "least" but SQL uses DESC/MAX)
- The SQL filters on the wrong entity (e.g. question asks about "EMEA" but SQL filters "APAC")

Answer "yes" if the SQL reasonably addresses the core intent of the question, even if it doesn't cover every detail.

Respond with ONLY "yes" or "no"."""

SYNTHESIS_PROMPT = """Answer the user's question by combining results from multiple data sources.

Question: {question}

Data sources:
{results_text}

Rules:
- Lead with the direct answer in the FIRST sentence — no preamble
- **Bold** key values, names, and numbers using markdown
- For multiple findings, use a markdown bullet list (each item on its own line starting with "- ")
- NEVER use inline bullets like "• item1 • item2" — always use markdown list format
- Be concise: aim for 2-4 sentences total
- Connect insights across sources where relevant
- If a source returned no results, mention it briefly
- Never repeat the question or say "based on the results"
- Never mention SQL, queries, or databases"""

ASSISTANT_PROMPT = """You are a friendly, helpful assistant for a multi-agent data analytics system.

You are powered by a supervisor that routes questions to specialized Genie Space sub-agents.
Here are the available Genie Spaces:
{spaces_detail}
{memory_section}
Conversation history:
{history}

The user says: {question}

Your role:
- For greetings or small talk, respond warmly and concisely.
- If you have user memory context above, USE it to personalize your response (e.g. greet the user by name, acknowledge their role or preferences).
- For questions about the system (capabilities, available spaces, how it works), provide accurate, structured information based on the Genie Spaces listed above.
- If they ask what you can do, explain based on the spaces and encourage them to ask a data question.
- If they ask about past conversation, refer to the history above.
- Keep responses concise and friendly.
Do NOT attempt to answer data questions yourself — just suggest they ask directly."""

_TITLE_PROMPT = """Generate a very short title (max 6 words) that summarizes this conversation topic.

User question: {question}
{response_hint}

Rules:
- Return ONLY the title text, nothing else
- Do NOT use quotes around the title
- Be concise and descriptive (e.g. "COVID Vaccine Stockout Analysis")
- If it's a greeting or meta question, use a generic title like "General Conversation"

Title:"""

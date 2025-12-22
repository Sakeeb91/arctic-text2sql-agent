"""
Unit tests for the Text2SQL engine module.

These tests verify the core orchestration logic, validation,
intent classification, and result handling.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.text2sql_engine import (
    QueryIntent,
    ReasoningStep,
    SchemaContext,
    SQLResult,
    SQLValidator,
    Text2SQLEngine,
    ValidationStatus,
    classify_query_intent,
    get_text2sql_engine,
    reset_text2sql_engine,
)
from db.schema import SchemaInfo

# =============================================================================
# Test Data Classes
# =============================================================================


class TestSchemaContext:
    """Tests for SchemaContext dataclass."""

    def test_creation(self, sample_schema: SchemaInfo) -> None:
        """Test SchemaContext creation."""
        context = SchemaContext(
            database_id="test_db",
            dialect="postgresql",
            schema_info=sample_schema,
            serialized_schema="Table: customers\n  - id (INTEGER)",
            table_names=["customers", "orders"],
        )

        assert context.database_id == "test_db"
        assert context.dialect == "postgresql"
        assert len(context.table_names) == 2

    def test_to_dict(self, sample_schema: SchemaInfo) -> None:
        """Test conversion to dictionary."""
        context = SchemaContext(
            database_id="test_db",
            dialect="postgresql",
            schema_info=sample_schema,
            serialized_schema="schema text",
            table_names=["customers", "orders"],
        )

        result = context.to_dict()

        assert result["database_id"] == "test_db"
        assert result["dialect"] == "postgresql"
        assert result["table_count"] == 2
        assert "table_names" in result


class TestReasoningStep:
    """Tests for ReasoningStep dataclass."""

    def test_creation(self) -> None:
        """Test ReasoningStep creation."""
        step = ReasoningStep(
            step=1,
            thought="Analyzing query structure",
            action="parse_query",
            observation="Query is a simple select",
        )

        assert step.step == 1
        assert step.thought == "Analyzing query structure"
        assert step.action == "parse_query"
        assert step.observation == "Query is a simple select"
        assert isinstance(step.timestamp, datetime)

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        step = ReasoningStep(
            step=1,
            thought="Test thought",
            action="test_action",
        )

        result = step.to_dict()

        assert result["step"] == 1
        assert result["thought"] == "Test thought"
        assert result["action"] == "test_action"
        assert result["observation"] is None
        assert "timestamp" in result


class TestSQLResult:
    """Tests for SQLResult dataclass."""

    def test_creation_minimal(self) -> None:
        """Test SQLResult creation with minimal fields."""
        result = SQLResult(
            sql="SELECT * FROM users",
            confidence=0.95,
            execution_time_ms=150.0,
            valid_syntax=True,
            validation_status=ValidationStatus.VALID,
            dialect="postgresql",
        )

        assert result.sql == "SELECT * FROM users"
        assert result.confidence == 0.95
        assert result.valid_syntax is True
        assert result.validation_status == ValidationStatus.VALID
        assert result.intent == QueryIntent.UNKNOWN
        assert result.warnings == []

    def test_creation_full(self) -> None:
        """Test SQLResult creation with all fields."""
        result = SQLResult(
            sql="SELECT * FROM users",
            confidence=0.95,
            execution_time_ms=150.0,
            valid_syntax=True,
            validation_status=ValidationStatus.VALID,
            dialect="postgresql",
            intent=QueryIntent.SELECT,
            warnings=["Low confidence warning"],
            reasoning_trace=[ReasoningStep(step=1, thought="Test thought")],
            execution_results=[{"id": 1, "name": "Test"}],
            row_count=1,
            metadata={"tokens": 50},
        )

        assert result.intent == QueryIntent.SELECT
        assert len(result.warnings) == 1
        assert len(result.reasoning_trace) == 1
        assert result.row_count == 1

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = SQLResult(
            sql="SELECT 1",
            confidence=0.9,
            execution_time_ms=100.0,
            valid_syntax=True,
            validation_status=ValidationStatus.VALID,
            dialect="postgresql",
        )

        data = result.to_dict()

        assert data["sql"] == "SELECT 1"
        assert data["confidence"] == 0.9
        assert data["validation_status"] == "valid"
        assert data["intent"] == "unknown"


# =============================================================================
# Test Query Intent Classification
# =============================================================================


class TestQueryIntentClassification:
    """Tests for query intent classification."""

    def test_select_intent(self) -> None:
        """Test classification of simple SELECT queries."""
        queries = [
            "Show all customers",
            "List all orders",
            "Find users from California",
            "Get all products",
            "Display employee names",
            "What are the products?",
        ]

        for query in queries:
            intent = classify_query_intent(query)
            assert intent == QueryIntent.SELECT, f"Failed for: {query}"

    def test_aggregate_intent(self) -> None:
        """Test classification of aggregation queries."""
        queries = [
            "How many customers are there?",
            "Count all orders",
            "What is the total revenue?",
            "Calculate the sum of amounts",
            "What is the average order value?",
            "Find the maximum price",
            "Group orders by customer",
        ]

        for query in queries:
            intent = classify_query_intent(query)
            assert intent == QueryIntent.AGGREGATE, f"Failed for: {query}"

    def test_join_intent(self) -> None:
        """Test classification of JOIN queries."""
        queries = [
            "Show customers with their orders",
            "List products along with their categories",
            "Display orders per customer",
            "Get employees and their departments",
        ]

        for query in queries:
            intent = classify_query_intent(query)
            assert intent == QueryIntent.JOIN, f"Failed for: {query}"

    def test_subquery_intent(self) -> None:
        """Test classification of subquery queries."""
        queries = [
            "Who has the most orders?",
            "Which customer has the highest revenue?",
            "Show top 10 products",
            "Find customers with more than 5 orders",
        ]

        for query in queries:
            intent = classify_query_intent(query)
            assert intent == QueryIntent.SUBQUERY, f"Failed for: {query}"

    def test_unknown_intent(self) -> None:
        """Test classification of ambiguous queries."""
        queries = [
            "customers California",
            "hello world",
        ]

        for query in queries:
            intent = classify_query_intent(query)
            assert intent == QueryIntent.UNKNOWN, f"Failed for: {query}"


# =============================================================================
# Test SQL Validator
# =============================================================================


class TestSQLValidator:
    """Tests for SQLValidator class."""

    def test_valid_select(self) -> None:
        """Test validation of valid SELECT queries."""
        validator = SQLValidator()

        valid_queries = [
            "SELECT * FROM users",
            "SELECT id, name FROM customers WHERE state = 'CA'",
            "SELECT COUNT(*) FROM orders",
            "WITH cte AS (SELECT * FROM users) SELECT * FROM cte",
        ]

        for sql in valid_queries:
            status, errors = validator.validate(sql)
            assert status == ValidationStatus.VALID, f"Failed for: {sql}"
            assert len(errors) == 0

    def test_invalid_syntax_empty(self) -> None:
        """Test validation of empty query."""
        validator = SQLValidator()

        status, errors = validator.validate("")
        assert status == ValidationStatus.INVALID_SYNTAX
        assert "empty" in errors[0].lower()

    def test_invalid_syntax_wrong_start(self) -> None:
        """Test validation of query not starting with SELECT/WITH."""
        validator = SQLValidator()

        status, errors = validator.validate("INSERT INTO users VALUES (1)")
        assert status == ValidationStatus.INVALID_SYNTAX
        assert "must start with" in errors[0].lower()

    def test_invalid_syntax_unbalanced_parens(self) -> None:
        """Test validation of unbalanced parentheses."""
        validator = SQLValidator()

        status, errors = validator.validate("SELECT * FROM users WHERE (id = 1")
        assert status == ValidationStatus.INVALID_SYNTAX
        assert "parentheses" in errors[0].lower()

    def test_dangerous_keywords(self) -> None:
        """Test detection of dangerous keywords."""
        validator = SQLValidator(allow_mutations=False)

        dangerous_queries = [
            "SELECT * FROM users; DROP TABLE users",
            "SELECT * FROM users; DELETE FROM users",
            "SELECT * FROM users; UPDATE users SET name='test'",
        ]

        for sql in dangerous_queries:
            status, errors = validator.validate(sql)
            assert status == ValidationStatus.DANGEROUS_QUERY, f"Failed for: {sql}"

    def test_injection_patterns(self) -> None:
        """Test detection of SQL injection patterns."""
        validator = SQLValidator()

        injection_queries = [
            "SELECT * FROM users WHERE id = 1 OR 1=1",
            "SELECT * FROM users; -- DROP TABLE",
            "SELECT * FROM users UNION SELECT * FROM passwords",
        ]

        for sql in injection_queries:
            status, errors = validator.validate(sql)
            assert status == ValidationStatus.DANGEROUS_QUERY, f"Failed for: {sql}"

    def test_schema_alignment(self, sample_schema: SchemaInfo) -> None:
        """Test schema alignment validation."""
        validator = SQLValidator()

        context = SchemaContext(
            database_id="test",
            dialect="postgresql",
            schema_info=sample_schema,
            serialized_schema="",
            table_names=["customers", "orders"],
        )

        # Valid table
        status, errors = validator.validate(
            "SELECT * FROM customers",
            schema_context=context,
        )
        assert status == ValidationStatus.VALID

        # Invalid table
        status, errors = validator.validate(
            "SELECT * FROM nonexistent_table",
            schema_context=context,
        )
        assert status == ValidationStatus.SCHEMA_MISMATCH
        assert "not found" in errors[0].lower()

    def test_allow_mutations(self) -> None:
        """Test validator with mutations allowed."""
        validator = SQLValidator(allow_mutations=True)

        # DROP is still blocked by injection pattern check
        # But UPDATE in a SELECT context should pass
        status, errors = validator.validate("SELECT * FROM users")
        assert status == ValidationStatus.VALID

    def test_semantic_aggregate_warning(self) -> None:
        """Test semantic warnings for missing aggregation."""
        validator = SQLValidator()
        query = "How many customers do we have?"
        intent = classify_query_intent(query)

        feedback = validator.check_semantics(
            natural_query=query,
            sql="SELECT * FROM customers",
            intent=intent,
        )

        assert any("aggregation" in warning.lower() for warning in feedback.warnings)
        assert feedback.suggestions

    def test_semantic_join_warning(self) -> None:
        """Test semantic warnings for missing JOIN."""
        validator = SQLValidator()
        query = "List customers with their orders"
        intent = classify_query_intent(query)

        feedback = validator.check_semantics(
            natural_query=query,
            sql="SELECT * FROM customers",
            intent=intent,
        )

        assert any("join" in warning.lower() for warning in feedback.warnings)

    def test_semantic_top_limit_warning(self) -> None:
        """Test semantic warnings for missing LIMIT."""
        validator = SQLValidator()
        query = "Show top 5 products by revenue"
        intent = classify_query_intent(query)

        feedback = validator.check_semantics(
            natural_query=query,
            sql="SELECT * FROM products ORDER BY revenue DESC",
            intent=intent,
        )

        assert any("limit" in warning.lower() for warning in feedback.warnings)
        assert any(
            "limit 5" in suggestion.lower() for suggestion in feedback.suggestions
        )


# =============================================================================
# Test Text2SQL Engine
# =============================================================================


class TestText2SQLEngine:
    """Tests for Text2SQLEngine class."""

    @pytest.fixture
    def mock_db_manager(self) -> MagicMock:
        """Create mock database manager."""
        manager = MagicMock()
        manager.engine = MagicMock()
        manager.dialect = "postgresql"
        manager.session = MagicMock()
        return manager

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Provide settings with agent and resilience defaults."""
        settings = MagicMock()
        settings.agent = MagicMock(
            min_confidence=0.7,
            max_steps=3,
            enable_validation=True,
        )
        settings.resilience = MagicMock(
            failure_threshold=3,
            recovery_timeout_seconds=30,
            half_open_max_attempts=1,
            backoff_base_seconds=0.1,
            backoff_max_seconds=0.2,
            fallback_enabled=True,
        )
        settings.cache = MagicMock(enabled=False)
        settings.huggingface = MagicMock(model_name="test-model")
        settings.multi_database = MagicMock(enabled=False)
        return settings

    def test_initialization(
        self, mock_db_manager: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Test engine initialization."""
        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):

            engine = Text2SQLEngine(mock_db_manager)

            assert engine._min_confidence == 0.7
            assert engine._max_retries == 3
            assert engine._enable_validation is True
            assert engine._resilience_settings is mock_settings.resilience

    def test_initialization_custom_params(
        self, mock_db_manager: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Test engine initialization with custom parameters."""
        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):

            engine = Text2SQLEngine(
                mock_db_manager,
                min_confidence=0.5,
                max_retries=5,
                enable_validation=False,
            )

            assert engine._min_confidence == 0.5
            assert engine._max_retries == 5
            assert engine._enable_validation is False

    def test_schema_cache_invalidation(
        self, mock_db_manager: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Test schema cache invalidation."""
        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):

            engine = Text2SQLEngine(mock_db_manager)

            # Add fake cache entries
            engine._schema_cache["db1"] = MagicMock()
            engine._schema_cache["db2"] = MagicMock()

            # Invalidate specific
            engine.invalidate_schema_cache("db1")
            assert "db1" not in engine._schema_cache
            assert "db2" in engine._schema_cache

            # Invalidate all
            engine.invalidate_schema_cache()
            assert len(engine._schema_cache) == 0

    @pytest.mark.asyncio
    async def test_execute_sql_uses_safe_executor(
        self,
        mock_db_manager: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Test execute_sql delegates to SafeQueryExecutor."""
        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):
            engine = Text2SQLEngine(mock_db_manager)

            session = AsyncMock()
            session_cm = AsyncMock()
            session_cm.__aenter__.return_value = session
            session_cm.__aexit__.return_value = None
            mock_db_manager.session.return_value = session_cm

            from db.executor import QueryResult

            query_result = QueryResult(
                success=True,
                sql="SELECT 1",
                rows=[{"id": 1}],
                row_count=1,
            )

            executor = AsyncMock()
            executor.execute.return_value = query_result

            with patch(
                "db.executor.SafeQueryExecutor", return_value=executor
            ) as mock_executor:
                result = await engine.execute_sql(
                    "SELECT 1",
                    database_id="test_db",
                    max_rows=5,
                )

            assert result is query_result
            mock_executor.assert_called_once_with(
                session=session,
                allow_mutations=False,
                max_rows=5,
                database_id="test_db",
                dialect="postgresql",
            )
            executor.execute.assert_awaited_once_with("SELECT 1")

    @pytest.mark.asyncio
    async def test__execute_sql_threads_database_id(
        self,
        mock_db_manager: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Test _execute_sql forwards database_id to execute_sql."""
        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):
            engine = Text2SQLEngine(mock_db_manager)

            mocked_result = MagicMock(rows=[{"id": 1}], row_count=1)
            with patch.object(
                engine,
                "execute_sql",
                new=AsyncMock(return_value=mocked_result),
            ) as mock_execute:
                rows, row_count = await engine._execute_sql(
                    "SELECT 1",
                    max_rows=25,
                    database_id="test_db",
                )

            mock_execute.assert_awaited_once_with(
                sql="SELECT 1",
                database_id="test_db",
                max_rows=25,
            )
            assert rows == [{"id": 1}]
            assert row_count == 1

    @pytest.mark.asyncio
    async def test_validate_sql(
        self,
        mock_db_manager: MagicMock,
        sample_schema: SchemaInfo,
        mock_settings: MagicMock,
    ) -> None:
        """Test SQL validation method."""
        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):

            engine = Text2SQLEngine(mock_db_manager)

            # Mock schema context
            with patch.object(engine, "_get_schema_context") as mock_get_schema:
                mock_get_schema.return_value = SchemaContext(
                    database_id="test",
                    dialect="postgresql",
                    schema_info=sample_schema,
                    serialized_schema="",
                    table_names=["customers", "orders"],
                )

                # Valid SQL
                is_valid, errors, warnings = await engine.validate_sql(
                    "SELECT * FROM customers",
                    "test_db",
                )
                assert is_valid is True
                assert len(errors) == 0

                # Invalid SQL (wrong table)
                is_valid, errors, warnings = await engine.validate_sql(
                    "SELECT * FROM unknown_table",
                    "test_db",
                )
                assert is_valid is False
                assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_generate_with_retry_uses_fallback_when_circuit_open(
        self,
        mock_db_manager: MagicMock,
        sample_schema: SchemaInfo,
        mock_settings: MagicMock,
    ) -> None:
        """Ensure circuit breaker open state triggers fallback response."""
        mock_settings.resilience.recovery_timeout_seconds = 60

        with patch("app.text2sql_engine.get_settings", return_value=mock_settings):
            engine = Text2SQLEngine(mock_db_manager)
            engine._circuit_breaker.state.state = "open"
            engine._circuit_breaker.state.opened_at = datetime.utcnow()

            schema_context = SchemaContext(
                database_id="test_db",
                dialect="postgresql",
                schema_info=sample_schema,
                serialized_schema="schema",
                table_names=["customers"],
            )

            result, warnings = await engine._generate_with_retry(
                natural_query="Show customers",
                schema_context=schema_context,
                intent=QueryIntent.SELECT,
            )

            assert result.metadata.get("fallback") is True
            assert any("circuit" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_resolve_database_context_uses_registry(
        self,
        mock_db_manager: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Test registry-based context resolution when enabled."""
        mock_settings.multi_database.enabled = True

        registered = MagicMock()
        registered.engine = MagicMock()
        registered.config.dialect = MagicMock()
        registered.config.dialect.value = "postgresql"

        registry = MagicMock()
        registry.get_database.return_value = registered
        registry.session.return_value = "session_ctx"

        with (
            patch("app.text2sql_engine.get_settings", return_value=mock_settings),
            patch("app.text2sql_engine.get_database_registry", return_value=registry),
        ):
            engine = Text2SQLEngine(mock_db_manager)
            context = await engine._resolve_database_context("analytics")

        assert context.database_id == "analytics"
        assert context.dialect == "postgresql"
        assert context.session_provider() == "session_ctx"


# =============================================================================
# Test Global Engine Management
# =============================================================================


class TestGlobalEngineManagement:
    """Tests for global engine management functions."""

    def test_reset_text2sql_engine(self) -> None:
        """Test resetting the global engine."""
        import app.text2sql_engine as module

        # Set a mock engine
        module._text2sql_engine = MagicMock()
        assert module._text2sql_engine is not None

        # Reset
        reset_text2sql_engine()
        assert module._text2sql_engine is None

    @pytest.mark.asyncio
    async def test_get_text2sql_engine(self) -> None:
        """Test getting the global engine."""
        reset_text2sql_engine()

        with patch("db.connection.get_database") as mock_get_db:
            mock_db = MagicMock()
            mock_db.engine = MagicMock()
            mock_get_db.return_value = mock_db

            with patch("app.config.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    agent=MagicMock(
                        min_confidence=0.7,
                        max_steps=3,
                        enable_validation=True,
                    ),
                    resilience=MagicMock(
                        failure_threshold=3,
                        recovery_timeout_seconds=30,
                        half_open_max_attempts=1,
                        backoff_base_seconds=0.1,
                        backoff_max_seconds=0.2,
                        fallback_enabled=True,
                    ),
                    cache=MagicMock(enabled=False),
                    huggingface=MagicMock(model_name="test-model"),
                    multi_database=MagicMock(enabled=False),
                )

                engine = await get_text2sql_engine()

                assert engine is not None
                assert isinstance(engine, Text2SQLEngine)

                # Should return same instance
                engine2 = await get_text2sql_engine()
                assert engine is engine2

        # Clean up
        reset_text2sql_engine()


# =============================================================================
# Test Validation Status Enum
# =============================================================================


class TestValidationStatus:
    """Tests for ValidationStatus enum."""

    def test_enum_values(self) -> None:
        """Test validation status enum values."""
        assert ValidationStatus.VALID.value == "valid"
        assert ValidationStatus.INVALID_SYNTAX.value == "invalid_syntax"
        assert ValidationStatus.SCHEMA_MISMATCH.value == "schema_mismatch"
        assert ValidationStatus.DANGEROUS_QUERY.value == "dangerous_query"
        assert ValidationStatus.NOT_VALIDATED.value == "not_validated"


class TestQueryIntent:
    """Tests for QueryIntent enum."""

    def test_enum_values(self) -> None:
        """Test query intent enum values."""
        assert QueryIntent.SELECT.value == "select"
        assert QueryIntent.AGGREGATE.value == "aggregate"
        assert QueryIntent.JOIN.value == "join"
        assert QueryIntent.SUBQUERY.value == "subquery"
        assert QueryIntent.UNKNOWN.value == "unknown"

"""
Unit tests for RequestSigner.

Tests HMAC-SHA256 signing and parameter handling.
"""

import pytest

from arbitrage.execution.signer import OrderSignatureCache, RequestSigner


class TestRequestSigner:
    """Tests for RequestSigner."""

    @pytest.fixture
    def signer(self) -> RequestSigner:
        """Create a test signer."""
        return RequestSigner("test_secret_key")

    def test_sign_basic(self, signer: RequestSigner) -> None:
        """Test basic signature generation."""
        query_string = "symbol=BTCUSDT&side=BUY&type=MARKET"

        signature = signer.sign(query_string)

        # Signature should be 64 character hex string
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_deterministic(self, signer: RequestSigner) -> None:
        """Test that same input produces same signature."""
        query_string = "symbol=BTCUSDT&side=BUY&type=MARKET"

        sig1 = signer.sign(query_string)
        sig2 = signer.sign(query_string)

        assert sig1 == sig2

    def test_sign_different_inputs(self, signer: RequestSigner) -> None:
        """Test that different inputs produce different signatures."""
        sig1 = signer.sign("symbol=BTCUSDT")
        sig2 = signer.sign("symbol=ETHUSDT")

        assert sig1 != sig2

    def test_sign_params(self, signer: RequestSigner) -> None:
        """Test signing parameter dict."""
        params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.001",
        }

        result = signer.sign_params(params)

        # Should include timestamp and signature
        assert "timestamp=" in result
        assert "signature=" in result
        assert "symbol=BTCUSDT" in result

    def test_sign_params_adds_timestamp(self, signer: RequestSigner) -> None:
        """Test that timestamp is added if not present."""
        params = {"symbol": "BTCUSDT"}

        result = signer.sign_params(params)

        assert "timestamp=" in result

    def test_sign_params_preserves_timestamp(self, signer: RequestSigner) -> None:
        """Test that existing timestamp is preserved."""
        params = {
            "symbol": "BTCUSDT",
            "timestamp": 1234567890000,
        }

        result = signer.sign_params(params)

        assert "timestamp=1234567890000" in result

    def test_create_signed_params(self, signer: RequestSigner) -> None:
        """Test creating signed params dict."""
        params = {
            "symbol": "BTCUSDT",
            "side": "BUY",
        }

        result = signer.create_signed_params(params)

        assert "symbol" in result
        assert "side" in result
        assert "timestamp" in result
        assert "signature" in result
        assert isinstance(result["signature"], str)

    def test_different_secrets_different_signatures(self) -> None:
        """Test that different secrets produce different signatures."""
        signer1 = RequestSigner("secret1")
        signer2 = RequestSigner("secret2")

        query = "symbol=BTCUSDT&timestamp=123456789"

        sig1 = signer1.sign(query)
        sig2 = signer2.sign(query)

        assert sig1 != sig2


class TestOrderSignatureCache:
    """Tests for OrderSignatureCache."""

    @pytest.fixture
    def cache(self) -> OrderSignatureCache:
        """Create a test cache."""
        signer = RequestSigner("test_secret")
        return OrderSignatureCache(signer)

    def test_precompute_order_base(self, cache: OrderSignatureCache) -> None:
        """Test precomputing order base params."""
        cache_key = cache.precompute_order_base(
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="IOC",
        )

        assert cache_key == "BTCUSDT_BUY_LIMIT"
        assert "BTCUSDT_BUY_LIMIT" in cache._static_params

    def test_get_signed_order_params(self, cache: OrderSignatureCache) -> None:
        """Test getting signed order params."""
        cache_key = cache.precompute_order_base(
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
            time_in_force="IOC",
        )

        result = cache.get_signed_order_params(
            cache_key=cache_key,
            quantity=0.001,
            price=50000.0,
        )

        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["type"] == "LIMIT"
        assert "quantity" in result
        assert "price" in result
        assert "timestamp" in result
        assert "signature" in result

    def test_get_signed_order_params_missing_key(
        self, cache: OrderSignatureCache
    ) -> None:
        """Test error on missing cache key."""
        with pytest.raises(KeyError):
            cache.get_signed_order_params(
                cache_key="nonexistent",
                quantity=0.001,
            )

    def test_quantity_formatting(self, cache: OrderSignatureCache) -> None:
        """Test that quantities are formatted without trailing zeros."""
        cache_key = cache.precompute_order_base(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
        )

        result = cache.get_signed_order_params(
            cache_key=cache_key,
            quantity=0.00100000,
        )

        # Should be "0.001" not "0.00100000"
        assert result["quantity"] == "0.001"

    def test_price_formatting(self, cache: OrderSignatureCache) -> None:
        """Test that prices are formatted without trailing zeros."""
        cache_key = cache.precompute_order_base(
            symbol="BTCUSDT",
            side="BUY",
            order_type="LIMIT",
        )

        result = cache.get_signed_order_params(
            cache_key=cache_key,
            quantity=0.001,
            price=50000.00000000,
        )

        # Should be "50000" not "50000.00000000"
        assert result["price"] == "50000"

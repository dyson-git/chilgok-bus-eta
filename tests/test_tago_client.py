import pytest
import requests
from collector.models import ArrivalObservation
from collector.tago_client import get_arrivals


def test_get_arrivals_parses_multiple_items(monkeypatch):
    """Test parsing when items.item is a list"""
    mock_response = {
        "response": {
            "body": {
                "items": {
                    "item": [
                        {"routeid": "GGB123", "routeno": "250", "arrtime": 300},
                        {"routeid": "GGB456", "routeno": "251", "arrtime": 720}
                    ]
                }
            }
        }
    }

    def mock_get(url, params=None):
        class MockResponse:
            def json(self):
                return mock_response
        return MockResponse()

    monkeypatch.setattr(requests, "get", mock_get)
    result = get_arrivals("key", "37050", "DGB7021234")
    assert result == [
        ArrivalObservation("GGB123", "250", 5.0),
        ArrivalObservation("GGB456", "251", 12.0)
    ]


def test_get_arrivals_normalizes_single_item_dict(monkeypatch):
    """Test normalization when items.item is a single dict instead of a list"""
    mock_response = {
        "response": {
            "body": {
                "items": {
                    "item": {"routeid": "GGB789", "routeno": "252", "arrtime": 180}
                }
            }
        }
    }

    def mock_get(url, params=None):
        class MockResponse:
            def json(self):
                return mock_response
        return MockResponse()

    monkeypatch.setattr(requests, "get", mock_get)
    result = get_arrivals("key", "37050", "DGB7021234")
    assert len(result) == 1
    assert result[0] == ArrivalObservation("GGB789", "252", 3.0)


def test_get_arrivals_returns_empty_list_when_no_buses(monkeypatch):
    """Test empty string items response (public data API quirk for no buses)"""
    mock_response = {
        "response": {
            "body": {
                "items": ""
            }
        }
    }

    def mock_get(url, params=None):
        class MockResponse:
            def json(self):
                return mock_response
        return MockResponse()

    monkeypatch.setattr(requests, "get", mock_get)
    result = get_arrivals("key", "37050", "DGB7021234")
    assert result == []

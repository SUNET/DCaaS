"""Tests for Pydantic models and validation."""

import pytest
from pydantic import ValidationError

from app.models import RegisterServerRequest


class TestRegisterServerRequest:
    def test_valid_mac_plain(self):
        req = RegisterServerRequest(
            bmc_mac="3CECEFA19CE8",
            ipmi_password="TestPass123",
            site="dcoa",
            location="rb06",
            rack="rb06",
            position=31,
            device_type="supermicro-1u",
            device_role="k8s-worker",
        )
        assert req.bmc_mac == "3CECEFA19CE8"

    def test_valid_mac_with_colons(self):
        req = RegisterServerRequest(
            bmc_mac="3C:EC:EF:A1:9C:E8",
            ipmi_password="TestPass123",
            site="dcoa",
            location="rb06",
            rack="rb06",
            position=31,
            device_type="supermicro-1u",
            device_role="k8s-worker",
        )
        assert req.bmc_mac == "3CECEFA19CE8"

    def test_valid_mac_lowercase(self):
        req = RegisterServerRequest(
            bmc_mac="3cecefa19ce8",
            ipmi_password="test",
            site="dcoa",
            location="rb06",
            rack="rb06",
            position=1,
            device_type="supermicro-1u",
            device_role="k8s-worker",
        )
        assert req.bmc_mac == "3CECEFA19CE8"

    def test_invalid_mac_too_short(self):
        with pytest.raises(ValidationError, match="12 hex characters"):
            RegisterServerRequest(
                bmc_mac="3CECEF",
                ipmi_password="test",
                site="dcoa",
                location="rb06",
                rack="rb06",
                position=1,
                device_type="supermicro-1u",
                device_role="k8s-worker",
            )

    def test_invalid_mac_not_hex(self):
        with pytest.raises(ValidationError, match="12 hex characters"):
            RegisterServerRequest(
                bmc_mac="ZZZZZZZZZZZZ",
                ipmi_password="test",
                site="dcoa",
                location="rb06",
                rack="rb06",
                position=1,
                device_type="supermicro-1u",
                device_role="k8s-worker",
            )

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            RegisterServerRequest(
                bmc_mac="3CECEFA19CE8",
                ipmi_password="",
                site="dcoa",
                location="rb06",
                rack="rb06",
                position=1,
                device_type="supermicro-1u",
                device_role="k8s-worker",
            )

    def test_position_out_of_range(self):
        with pytest.raises(ValidationError):
            RegisterServerRequest(
                bmc_mac="3CECEFA19CE8",
                ipmi_password="test",
                site="dcoa",
                location="rb06",
                rack="rb06",
                position=0,
                device_type="supermicro-1u",
                device_role="k8s-worker",
            )

    def test_formatted_mac(self):
        req = RegisterServerRequest(
            bmc_mac="3CECEFA19CE8",
            ipmi_password="test",
            site="dcoa",
            location="rb06",
            rack="rb06",
            position=31,
            device_type="supermicro-1u",
            device_role="k8s-worker",
        )
        assert req.formatted_mac() == "3c:ec:ef:a1:9c:e8"

    def test_device_name(self):
        req = RegisterServerRequest(
            bmc_mac="3CECEFA19CE8",
            ipmi_password="test",
            site="sunetdco",
            location="dcoa",
            rack="RA07",
            position=45,
            device_type="supermicro-1u",
            device_role="k8s-worker",
        )
        assert req.device_name() == "dcoa-ra07u45"

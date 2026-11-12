# Runs with no cloud credentials: the provider is mocked and every run is plan-only.
mock_provider "azurerm" {}

variables {
  name              = "allowed-locations"
  allowed_locations = ["westeurope", "northeurope"]
}

run "renders_the_allowed_locations" {
  command = plan

  assert {
    condition     = jsondecode(azurerm_policy_definition.allowed_locations.policy_rule)["if"]["not"]["in"] == ["westeurope", "northeurope"]
    error_message = "The rendered rule must list exactly the allowed locations."
  }

  assert {
    condition     = jsondecode(azurerm_policy_definition.allowed_locations.policy_rule)["then"]["effect"] == "Deny"
    error_message = "The default effect must be Deny."
  }
}

run "rejects_an_empty_location_list" {
  command = plan

  variables {
    allowed_locations = []
  }

  expect_failures = [var.allowed_locations]
}

run "rejects_an_unknown_effect" {
  command = plan

  variables {
    effect = "Append"
  }

  expect_failures = [var.effect]
}

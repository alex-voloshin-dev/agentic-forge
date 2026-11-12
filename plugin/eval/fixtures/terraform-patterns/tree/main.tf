# Allowed-locations policy (allowed-locations policy module, terraform-patterns Tier-2 eval fixture).
resource "azurerm_policy_definition" "allowed_locations" {
  name         = var.name
  policy_type  = "Custom"
  mode         = "Indexed"
  display_name = "Allowed locations (${var.name})"

  policy_rule = jsonencode({
    "if" = {
      "not" = {
        "field" = "location"
        "in"    = var.allowed_locations
      }
    }
    "then" = {
      "effect" = var.effect
    }
  })
}

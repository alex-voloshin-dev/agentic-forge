output "policy_definition_id" {
  description = "ID of the policy definition, for an assignment."
  value       = azurerm_policy_definition.allowed_locations.id
}

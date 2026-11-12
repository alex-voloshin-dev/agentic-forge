variable "name" {
  description = "Name of the policy definition."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{3,64}$", var.name))
    error_message = "name must be 3-64 lowercase letters, digits or hyphens."
  }
}

variable "allowed_locations" {
  description = "Azure regions resources may be created in."
  type        = list(string)

  validation {
    condition     = length(var.allowed_locations) > 0
    error_message = "allowed_locations must name at least one region."
  }
}

variable "effect" {
  description = "Policy effect when a resource is outside the allowed locations."
  type        = string
  default     = "Deny"

  validation {
    condition     = contains(["Audit", "Deny", "Disabled"], var.effect)
    error_message = "effect must be Audit, Deny or Disabled."
  }
}

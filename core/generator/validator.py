"""
MCP schema validator.
Validates generated MCP server code against expected patterns
and runs a security audit for common issues.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    security_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "security_issues": self.security_issues,
        }


class MCPValidator:
    """Validate generated MCP code for correctness and security."""

    # Patterns that should exist in a valid Python FastMCP server
    REQUIRED_PATTERNS_PYTHON = [
        (r"from\s+mcp\.server\.fastmcp\s+import\s+FastMCP|from\s+fastmcp\s+import\s+FastMCP",
         "FastMCP import missing"),
        (r"FastMCP\(",                    "FastMCP instance not created"),
        (r"mcp\.run\(\)|if __name__",     "Entry point (mcp.run / __main__) missing"),
    ]

    # Patterns that indicate security issues
    SECURITY_BAD_PATTERNS = [
        (r"os\.environ\s*\[",             "Avoid os.environ[] — use os.getenv() with defaults"),
        (r"eval\s*\(",                    "eval() is dangerous — remove it"),
        (r"exec\s*\(",                    "exec() is dangerous — remove it"),
        (r"subprocess\.call\s*\(",        "Unvalidated subprocess call — sanitize inputs"),
        (r"password\s*=\s*['\"].+['\"]",  "Hardcoded password detected"),
        (r"secret\s*=\s*['\"].+['\"]",    "Hardcoded secret detected"),
        (r"api_key\s*=\s*['\"][A-Za-z0-9]{10,}['\"]", "Hardcoded API key detected"),
    ]

    def validate_python(self, code: str) -> ValidationResult:
        result = ValidationResult()

        # Required structure checks
        for pattern, msg in self.REQUIRED_PATTERNS_PYTHON:
            if not re.search(pattern, code, re.MULTILINE):
                result.errors.append(msg)
                result.valid = False

        # Warnings
        if "@mcp.tool()" not in code:
            result.warnings.append("No tools defined — the MCP server will be empty")

        if "httpx" not in code and "requests" not in code and "aiohttp" not in code:
            result.warnings.append("No HTTP client imported — tools may not be calling the API")

        if "os.getenv" not in code and "os.environ" not in code:
            result.warnings.append("No environment variable usage — credentials may be hardcoded")

        # Security audit
        from config import settings
        if settings.enable_security_audit:
            for pattern, msg in self.SECURITY_BAD_PATTERNS:
                if re.search(pattern, code, re.IGNORECASE):
                    result.security_issues.append(msg)

        return result

    def validate_nodejs(self, code: str) -> ValidationResult:
        result = ValidationResult()

        if "@modelcontextprotocol/sdk" not in code and "fastmcp" not in code:
            result.errors.append("MCP SDK import missing")
            result.valid = False

        if "server.tool(" not in code and "server.resource(" not in code:
            result.warnings.append("No tools or resources defined")

        for pattern, msg in self.SECURITY_BAD_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                result.security_issues.append(msg)

        return result

    def validate(self, files: dict[str, str], language: str = "python") -> ValidationResult:
        """Validate all files in the generated output."""
        combined = "\n".join(files.values())
        if language in ("python", "python_fastmcp"):
            return self.validate_python(combined)
        elif language in ("nodejs", "javascript", "typescript"):
            return self.validate_nodejs(combined)
        # For other languages, just do the security scan
        result = ValidationResult()
        for pattern, msg in self.SECURITY_BAD_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                result.security_issues.append(msg)
        return result

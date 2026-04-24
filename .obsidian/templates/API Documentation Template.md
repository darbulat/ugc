---
title: "{{endpoint_name}} API"
type: api-docs
method: {{http_method}}
path: {{endpoint_path}}
tags: [api, documentation]
---

# {{endpoint_name}}

## Endpoint
```
{{http_method}} {{endpoint_path}}
```

## Description
{{description}}

## Authentication
{{auth_method}}

## Request

### Headers
```
Content-Type: application/json
```

### Body
```json
{{request_body_example}}
```

### Query Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| {{param_1}} | {{type_1}} | {{required_1}} | {{description_1}} |

## Response

### Success (200)
```json
{{success_response_example}}
```

### Errors
| Status | Code | Message |
|--------|------|---------|
| 400 | {{error_code}} | {{error_message}} |
| 401 | UNAUTHORIZED | Missing or invalid authentication |

## Examples

### cURL
```bash
curl -X {{http_method}} {{endpoint_path}} \
  -H "Content-Type: application/json" \
  -d '{{request_body_example}}'
```

### Python
```python
{{python_example}}
```

## Related Endpoints
- [[{{related_endpoint_1}}]]

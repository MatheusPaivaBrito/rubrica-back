from http_client import print_result, request_json, service_url


def main() -> None:
    base_url = service_url("CORE_API_URL", "CORE_API_PORT", "8100")
    health_status, health_body = request_json("GET", f"{base_url}/health")
    print_result("core health", health_status, health_body)

    manifest_status, manifest_body = request_json("GET", f"{base_url}/ui-manifest")
    print_result("core empty ui manifest", manifest_status, manifest_body)


if __name__ == "__main__":
    main()

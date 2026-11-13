# Contributing to FlightCheck

Outside code contributions are currently deferred while the project establishes contribution terms suitable for FSL-1.1-MIT, its future MIT license, and any additional commercial licensing.

Bug reports, feature requests, and questions are welcome in [GitHub issues](https://github.com/spring-labs-inc/FlightCheck/issues). Describe the problem, expected behavior, reproduction steps, and relevant environment. Please keep reports free of credentials and private or customer information.

Please wait to submit outside code contributions, patches, diffs, or replacement implementations, including code offered through issues or email. Pull request creation is restricted to repository collaborators so maintainers can continue their normal PR workflow.

Collaborator access is a repository permission, not a transfer of copyright or an additional contribution license. Maintainers must have the necessary rights for material they include. Before accepting collaborator contributions, confirm the necessary rights, including a separate agreement when broader commercial licensing rights are needed. Collaborators may retain copyright while granting those rights. Before opening outside code intake, the project will establish and publish its contribution terms.

For licensing questions and commercial inquiries, contact [jeff@springfinance.io](mailto:jeff@springfinance.io). See the [licensing and adoption guide](docs/licensing.md). Subscriptions remain deferred.

## Run the FlightCheck tests

For work on FlightCheck itself, follow the repository's [development instructions](AGENTS.md). These checks verify FlightCheck; adopting projects use their own test commands.

From the FlightCheck checkout, activate a Python 3 virtual environment on a POSIX host. Install pytest in that environment and run the suite:

```sh
python3 -m pip install pytest
python3 -B -m unittest discover -s tests
```

The recorder integration tests invoke pytest. The HTTP status-card tests need permission to bind an ephemeral port on `127.0.0.1`.

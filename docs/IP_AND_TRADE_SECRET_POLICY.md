# ComputeMesh IP and trade-secret handling policy

This document is an engineering policy draft, not legal advice.

## Core rule

Information intended to qualify as a trade secret must never be committed to the public repository. Treat public Git history as permanent disclosure.

## Restricted categories

The following are `STRICT_PRIVATE` by default:

- production scheduler scoring logic, learned models, feature weights and coefficients
- network-wide performance datasets and topology history
- provider reliability/reputation raw data and graph structure
- fraud/abuse features, labels, thresholds and playbooks
- pricing elasticity, margins, take-rate logic and private quotes
- customer/provider matching and marketplace ranking logic
- private settlement, dispute and payout policies
- production signing keys and credentials
- unreleased research that creates material commercial advantage

## Access controls

For private repositories and data systems:

- least-privilege access
- mandatory MFA/SSO where available
- protected default branch and mandatory review
- no public forks
- secret scanning and push protection
- production secrets in KMS/HSM/secret manager, never Git
- separate read access for code, production data and signing material
- access logging and periodic access review
- immediate credential/key rotation after suspected disclosure

## Contributor/employee controls

Before granting access to `STRICT_PRIVATE` material, require appropriate confidentiality and IP-assignment terms. External contributions to the public project should have a documented inbound-license/contributor policy so ownership and relicensing rights are understood.

## AI tooling rule

Do not paste `STRICT_PRIVATE` source, datasets, credentials, scheduler weights, fraud rules or commercial parameters into third-party AI systems unless the applicable enterprise agreement and data controls have been approved for confidential source code. AI-generated code must not be assumed to create exclusivity; architectural ideas that are observable from public behavior may be independently reimplemented.

## API disclosure minimization

Production APIs expose only the minimum information needed for execution:

- opaque decision IDs
- selected placement and required execution parameters
- coarse eligibility/tier results
- signed quotes and settlement decisions

Never expose:

- rejected candidate lists
- candidate scores
- feature vectors
- raw reputation values
- global provider inventory
- internal pricing curves
- confidence/model diagnostics that make black-box extraction materially easier

## Review gate

Any public PR touching scheduler, pricing, reputation, fraud, marketplace ranking, control-plane orchestration or settlement must answer:

1. Does this disclose a production algorithm or only an interface/reference implementation?
2. Does it reveal data features, weights, thresholds or network-wide state?
3. Can the same result be achieved by publishing a schema/test fixture instead?
4. Has dependency direction remained `private -> public`, never `public -> private implementation`?
5. Does the change accidentally include secrets, private endpoints or production identifiers?

If any answer is uncertain, keep the implementation private and publish only the interoperable contract.

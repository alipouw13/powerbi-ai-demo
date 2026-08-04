# Brand icons (third-party)

Vendored logos for third-party systems that appear in this architecture but are
not in the official Microsoft Azure or Fabric icon sets. Resolved by
`cloudicons.py --provider brand` and embedded as base64 data URIs so the
generated diagrams stay self-contained and work offline.

| File | Product | Owner |
| --- | --- | --- |
| `github-copilot.png` | GitHub Copilot | GitHub, Inc. / Microsoft |

## Trademark

These logos are the trademarks of their respective owners and are included here
**for identification purposes only**, the same basis on which draw.io ships AWS
and Azure stencils. Use them only to identify the corresponding product in an
architecture diagram. Do not modify them or imply endorsement.

## Adding a brand icon

Drop a transparent-background `.png` or `.svg` here, named for the product. The
filename minus the extension becomes the searchable label. Prefer a square,
trimmed, transparent image so it sits cleanly on a card.

## GitHub Copilot is not Microsoft Copilot

They are different products with different marks. Do not use one for the other.

- **GitHub Copilot**, the developer experience in VS Code that talks to MCP
  servers, resolves as `icon="github copilot", provider="brand"`.
- **Copilot in Power BI** and **Fabric Copilot** use the official Fabric icon,
  `icon="copilot", provider="fabric"`.

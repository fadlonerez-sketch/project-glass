# Notifications

| Source | How it reaches the Dynamic Glass | Status |
|---|---|---|
| Glass itself (errors, "LaunchDeck isn't running", …) | Direct | Working |
| Garvis: approval requests (`CONFIRMATION_REQUESTED`) and errors | The Garvis adapter calls `notify.post` on the automation engine, which relays it to the Shell | Working; covered by unit tests on both sides |
| Windows notifications from other apps | `UserNotificationListener` | **Requires package identity.** See below |

Rules from Control Center › Notifications apply to all of them:
- presentation in the Dynamic Glass, as a banner, or silent;
- Do Not Disturb (only high priority gets through);
- a minimum priority;
- per-app *enabled* and *priority*.

The clock flyout keeps the last 50 notifications.

## Why Windows notifications need extra setup

Windows only lets apps with **package identity** read other apps' notifications (`UserNotificationListener`
and the `userNotificationListener` capability). Glass runs as plain Python, which has no package identity, so
until identity is added Glass reports `needs_identity` and shows only its own and Garvis's notifications. It
never scrapes Explorer's notification UI.

The supported way to give a desktop app identity is a **sparse package**: an MSIX with an external location.
`scripts/install-identity.ps1` does it in four steps:

1. downloads the Microsoft.Windows.SDK.BuildTools NuGet package (makeappx, signtool) and **refuses to use it** unless
   its hash matches the one you pass (`-BuildToolsSha512 '<Package hash from nuget.org>'` or `-BuildToolsSha256 <hex>`)
   and both tools carry a valid Microsoft Authenticode signature;
2. builds `ProjectGlass.Identity.msix` from `packaging/AppxManifest.xml`, pointing at the project folder, with the `userNotificationListener` capability;
3. creates a self-signed code-signing certificate with a **non-exportable** key in CurrentUser\My, signs from the store by
   thumbprint (no PFX file, no password), and trusts the public certificate in **CurrentUser\TrustedPeople**, which
   Microsoft documents as enough for a per-user sparse package, so no administrator approval is needed. If Windows still
   rejects it (0x800B0109), rerun with `-MachineWideTrust` to use LocalMachine\TrustedPeople (one administrator approval);
4. registers the package with `Add-AppxPackage -ExternalLocation`, and adds a **Project Glass (with notifications)** entry that starts the Shell through the package, so it runs with identity.

After that, the first start asks Windows for notification access. Allow it, or later in
Settings › Privacy & security › Notifications.

> **Not verified on this PC.** The script has not been run (it downloads the SDK tools and changes certificate
> stores), and whether CurrentUser trust suffices here is untested. The Glass side is implemented and tested only up to the `needs_identity`
> state: identity detection, access request, polling of new toasts, and the rules. Remove the package with
> `Get-AppxPackage ProjectGlass.Identity | Remove-AppxPackage`.

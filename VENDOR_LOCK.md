# Vendor Lock System

This document explains how the vendor lock mechanism protects `vendor/blueprint-framework` from unauthorized modifications.

## Overview

The vendor lock system requires a **password** to modify the vendored blueprint-framework. This ensures that the framework code cannot be modified by:
- Accidental direct edits
- Unauthorized AI modification
- Supply chain attacks

## Usage

### Lock the vendor (initial setup)

```bash
bpfw vendor-lock
# Enter password when prompted
```

This will:
1. Store an encrypted unlock key in `.vendor_lock/.vendor_unlock_key`
2. Sign the vendor lock state with HMAC-SHA256
3. Apply filesystem protection (chmod 444 on Linux, ACLs on Windows)
4. Mark vendor files with `git assume-unchanged` on NTFS/FUSE systems

### Unlock the vendor (before updates)

```bash
bpfw vendor-unlock
# Enter password when prompted
```

This will:
1. Verify the password against the stored encrypted key
2. Restore write permissions to vendor files
3. Remove `git assume-unchanged` flags
4. Allow `pip install -e vendor/blueprint-framework` to work

### Check vendor lock status

```bash
cat .vendor_lock/vendor_lock.json
```

The status field will show `"locked"` or `"unlocked"`.

## Protection Mechanisms

### On Linux (native filesystems)

- **Method**: `chmod 444` (read-only files)
- **Enforcement**: Kernel-level read-only attribute
- **Can be bypassed**: Root/sudo can still chmod files back

### On NTFS/FUSE (WSL, mounted drives)

- **Method**: `git assume-unchanged` flags
- **Enforcement**: Git ignores modifications to marked files
- **Can be bypassed**: Direct filesystem edits won't be tracked by git

### On Windows (native NTFS)

- **Method**: `icacls /deny` (ACL deny write permission)
- **Enforcement**: Access Control List at filesystem level
- **Can be bypassed**: Admin can modify ACLs

## Security Properties

### What is protected

- ✅ Prevents accidental modifications via normal file operations
- ✅ Prevents AI from modifying via bash/vim/cat
- ✅ Requires password to unlock
- ✅ Detects tampering via HMAC signatures
- ✅ Works across Linux, Windows, macOS

### What is NOT protected

- ⚠️ Root/admin can bypass filesystem protections
- ⚠️ Physical access can bypass protections
- ⚠️ On NTFS, direct binary edits might not be detected by git

## Architecture

### Files

- `.vendor_lock/vendor_lock.json` - Vendor lock state with HMAC signature
- `.vendor_lock/.vendor_unlock_key` - PBKDF2-derived encrypted key

### Implementation

The vendor lock system uses:
- **PBKDF2-SHA256** with 100,000 iterations for key derivation
- **HMAC-SHA256** for signing the lock state file
- **Filesystem-level protections** (chmod/icacls/git)
- **Atomic writes** for lock state to prevent corruption

## Example Workflow

```bash
# 1. Initial lock setup
$ bpfw vendor-lock
🔒 Configura contraseña para vendor:
Password: ****
✅ Vendor directory locked and protected

# 2. Vendor is now protected - edits are rejected
$ echo "test" >> vendor/blueprint-framework/src/bpfw/vendor/vendor_lock.py
# On Linux: "Permission denied"
# On NTFS: Git ignores the change

# 3. When you need to update the framework
$ bpfw vendor-unlock
🔓 Verifica contraseña para desbloquear vendor:
Password: ****
✅ Vendor directory unlocked

# 4. Now you can update
$ pip install -e vendor/blueprint-framework --upgrade

# 5. Re-lock when done
$ bpfw vendor-lock
🔒 Configura contraseña para vendor:
Password: ****
✅ Vendor directory locked and protected
```

## Security Model

The vendor lock is designed to prevent **unintentional** modifications and **unauthorized** modifications. It is not designed to protect against determined attacks by someone with:
- Root/admin access to the machine
- Physical access to the disk
- Control over the git repository

For production deployments, additional controls are recommended:
- Code signing and verification
- Containerization (immutable images)
- Supply chain security scanning
- Dependency pinning and auditing

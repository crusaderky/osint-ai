#!/bin/bash
# The branch dance for one checkout of this project. Sourced by
# `scripts/update-project.sh` and by `windows/update-installation.sh`; run
# directly, it updates the checkout you name.
#
# `main` is the published program. `staging` is the branch the assistant commits
# to and the branch the user publishes from. Both checkouts use this one
# implementation, and it does exactly this:
#
#   main     switch to it, fast-forward it to origin/main
#   staging  switch to it, fast-forward it to origin/staging, merge main into it
#
# A checkout without a `staging` branch - the WSL program checkout is cloned with
# `--branch main` on purpose - only needs its `main` fast-forwarded.
#
# Nothing here pushes, discards a commit, rebases or resolves a conflict, and no
# file is touched before every check has passed. A checkout this cannot update is
# left exactly as it was; a branch that moved on in two places is reported as
# needing attention and the update carries on with the rest of the work.
#
# Exit status: 0 updated, 1 refused with nothing changed, 2 updated but something
# above needs a human.

# A hook, an fsmonitor command or a pager planted in `.git` must not run here:
# the Windows checkout is writable by the assistant, and its `.git` with it, and
# this runs while a human is told the update is under way. `core.hooksPath`
# pointing at /dev/null is Git's documented way of switching hooks off.
OSINT_GIT_SAFE=(-c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.pager=cat)

# `https://github.com/o/r`, `...r.git` and `...r/` are the same repository, and
# GitHub does not distinguish case in an owner or repository name.
normalized_url() {
    local url=${1:-}
    url=${url%/}
    url=${url%.git}
    printf '%s' "${url,,}"
}

# sync_git <checkout> <git arguments...>
sync_git() {
    local checkout=$1
    shift
    command git -C "$checkout" "${OSINT_GIT_SAFE[@]}" "$@"
}

# sync_branches <checkout> [<origin the checkout must come from>]
sync_branches() {
    local checkout=${1:-} expected=${2:-}
    local attention=0 before after origin branch changes

    if [[ -z $checkout ]]; then
        printf 'sync_branches: name the checkout to update.\n' >&2
        return 1
    fi
    if [[ ! -d $checkout ]]; then
        printf 'There is no checkout at %s.\n' "$checkout" >&2
        return 1
    fi
    if ! sync_git "$checkout" rev-parse --git-dir >/dev/null 2>&1; then
        printf 'There is no Git checkout at %s.\n' "$checkout" >&2
        return 1
    fi

    if [[ -n $expected ]]; then
        origin=$(sync_git "$checkout" remote get-url origin 2>/dev/null || true)
        if [[ $(normalized_url "$origin") != "$(normalized_url "$expected")" ]]; then
            printf 'The checkout at %s fetches from %s, not from %s.\n' \
                "$checkout" "${origin:-nowhere}" "$expected" >&2
            printf 'Refusing to update it: correct the remote in your Git app, then try again.\n' >&2
            return 1
        fi
    fi

    # Uncommitted work is checked before anything moves. A branch switch would
    # either refuse halfway or take the changes along with it.
    changes=$(sync_git "$checkout" status --porcelain) || {
        printf 'Could not read the state of %s.\n' "$checkout" >&2
        return 1
    }
    if [[ -n $changes ]]; then
        printf 'The checkout at %s has changes Git has not saved yet:\n%s\n' "$checkout" "$changes" >&2
        printf 'Nothing was changed. Save or undo them, then run this again.\n' >&2
        return 1
    fi

    branch=$(sync_git "$checkout" symbolic-ref --quiet --short HEAD || true)
    if [[ -z $branch ]]; then
        printf 'The checkout at %s is not on a branch (detached HEAD).\n' "$checkout" >&2
        printf 'Nothing was changed. Put it back on main in your Git app, then try again.\n' >&2
        return 1
    fi
    if [[ $branch != main && $branch != staging ]]; then
        printf 'The checkout at %s is on the branch %s.\n' "$checkout" "$branch" >&2
        printf 'This update only handles main and staging. Nothing was changed.\n' >&2
        return 1
    fi

    if ! sync_git "$checkout" fetch --prune origin; then
        printf 'Could not reach the repository %s was cloned from. Nothing was changed.\n' \
            "$checkout" >&2
        return 1
    fi
    printf 'Updating %s\n' "$checkout"

    if sync_git "$checkout" show-ref --verify --quiet refs/heads/main; then
        sync_git "$checkout" checkout --quiet main
    elif sync_git "$checkout" show-ref --verify --quiet refs/remotes/origin/main; then
        sync_git "$checkout" checkout --quiet --track -b main origin/main
    else
        printf 'Neither %s nor its origin has a main branch.\n' "$checkout" >&2
        return 1
    fi
    before=$(sync_git "$checkout" rev-parse --short HEAD)
    if sync_git "$checkout" merge --ff-only origin/main >/dev/null 2>&1; then
        after=$(sync_git "$checkout" rev-parse --short HEAD)
        if [[ $before == "$after" ]]; then
            printf '  main     up to date (%s)\n' "$after"
        else
            printf '  main     fast-forwarded %s -> %s\n' "$before" "$after"
        fi
    else
        printf '  main     left at %s\n' "$before"
        printf 'ATTENTION: main and origin/main have both moved on in %s. Push or merge them in your Git app.\n' \
            "$checkout" >&2
        attention=1
    fi

    if ! sync_git "$checkout" show-ref --verify --quiet refs/heads/staging &&
        ! sync_git "$checkout" show-ref --verify --quiet refs/remotes/origin/staging; then
        # The WSL deployment's program checkout: main is the whole story there.
        printf '  staging  not in this checkout (main only)\n'
    else
        if sync_git "$checkout" show-ref --verify --quiet refs/heads/staging; then
            sync_git "$checkout" checkout --quiet staging
        else
            sync_git "$checkout" checkout --quiet -b staging origin/staging
        fi
        if sync_git "$checkout" show-ref --verify --quiet refs/remotes/origin/staging; then
            before=$(sync_git "$checkout" rev-parse --short HEAD)
            if sync_git "$checkout" merge --ff-only origin/staging >/dev/null 2>&1; then
                after=$(sync_git "$checkout" rev-parse --short HEAD)
                if [[ $before != "$after" ]]; then
                    printf '  staging  fast-forwarded %s -> %s\n' "$before" "$after"
                fi
            else
                printf 'ATTENTION: staging and origin/staging have both moved on in %s. Push or merge them in your Git app.\n' \
                    "$checkout" >&2
                attention=1
            fi
        fi
        # The published program comes back into the branch the user publishes
        # from. A real merge is needed only when staging holds commits GitHub has
        # never seen, which is the normal state of the assistant's checkout; the
        # user reviews and pushes the result.
        local -a identity=()
        if ! sync_git "$checkout" config --get user.name >/dev/null 2>&1 ||
            ! sync_git "$checkout" config --get user.email >/dev/null 2>&1; then
            identity=(-c user.name='OSINT AI update' -c user.email='update@osint-ai.invalid')
            printf '  note     this checkout has no Git identity, so the merge uses OSINT AI update <update@osint-ai.invalid>\n'
        fi
        before=$(sync_git "$checkout" rev-parse --short HEAD)
        if command git -C "$checkout" "${OSINT_GIT_SAFE[@]}" ${identity[@]+"${identity[@]}"} \
            merge --no-edit main >/dev/null 2>&1; then
            after=$(sync_git "$checkout" rev-parse --short HEAD)
            if [[ $before == "$after" ]]; then
                printf '  staging  already contains main\n'
            else
                printf '  staging  merged main (%s -> %s)\n' "$before" "$after"
            fi
        else
            # Never leave a conflicted merge behind for the user to discover.
            sync_git "$checkout" merge --abort >/dev/null 2>&1 || true
            printf 'ATTENTION: main does not merge into staging in %s without a conflict. It was undone, not resolved; this needs the maintainer.\n' \
                "$checkout" >&2
            attention=1
        fi
    fi

    if ((attention)); then
        printf '%s was updated, but something above needs your attention.\n' "$checkout"
        return 2
    fi
    printf '%s is up to date.\n' "$checkout"
    return 0
}

# Sourced by the two updaters. Run directly, it updates the checkout it is given.
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    set -euo pipefail
    if (( $# > 2 )); then
        printf 'Usage: %s <checkout> [<expected origin>]\n' "${BASH_SOURCE[0]}" >&2
        exit 2
    fi
    sync_branches "${1:-}" "${2:-}"
fi

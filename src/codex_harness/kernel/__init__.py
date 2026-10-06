"""Shared kernel of the Zeus target: identities, canonical JSON/digest, errors, clock and id-source
ports, six-W message values and the single runtime-policy definition.

Layer: kernel
Context: kernel
Owns: no bucket and no IO; every other context may import these values (§2.4)
Does not own: JSON-Schema validation (storage.adapters.message_schema), organization authority
(routing), context packets (context)
"""

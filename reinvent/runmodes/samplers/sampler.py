"""Base class for samplers

The sampling code is separate to facilitate sampling as a standalone module.
This class basically just serves as an "adaptor" of some kind because it
accepts all parameters needed for the model samplers.  Some of these parameters
are only needed by some model samplers.

FIXME: The alternative would be to remove this class and use a simple strategy
       pattern for the samplers.  This would mean that all samplers need to
       accept all parameters and all those classes need the boilerplate.  Also,
       the classes are not really needed and a simple function (with helper
       functions were needed) would suffice.
"""

from __future__ import annotations

__all__ = ["Sampler", "remove_duplicate_sequences", "validate_smiles", "INVALID_STR"]
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import List, Tuple, TYPE_CHECKING
import logging

import numpy as np
from rdkit import Chem

from reinvent.models.model_factory.sample_batch import SmilesState

if TYPE_CHECKING:
    from reinvent.runmodes.dtos import ChemistryHelpers
    from reinvent.models import ModelAdapter
    from reinvent.models.model_factory.sample_batch import SampleBatch
    from reinvent.chemistry import TransformationTokens


logger = logging.getLogger(__name__)

INVALID_STR = "INVALID"


@dataclass
class Sampler(ABC):
    """Base class for samplers"""

    model: ModelAdapter
    batch_size: int
    sample_strategy: str = "multinomial"  # Mol2Mol
    isomeric: bool = False  # Mol2Mol
    randomize_smiles: bool = True
    unique_sequences: bool = False  # backwards compatibility for R3
    chemistry: ChemistryHelpers = None
    tokens: TransformationTokens = None  # LinkInvent only
    temperature: float = 1.0

    @abstractmethod
    def sample(self, smilies: List[str]) -> SampleBatch:
        """Use provided SMILES list for sampling"""


def remove_duplicate_sequences(
    sampled: SampleBatch, is_reinvent: bool = False, is_mol2mol: bool = False
):
    """Remove duplicate sequences/SMILES

    This operates on the SMILES directly sampled from the model.  This means
    that not all duplicates will be removed here because the model can
    generated the same molecule with a different sequences.

    We keep this for backward compatibility with R3.

    :param sampled: sampled results from the model
    """

    orig_len = len(sampled.output)

    if is_reinvent:
        seq_string = np.array(sampled.output)
        sampled.items1 = sampled.items1.cpu()
    elif is_mol2mol:
        seq_string = np.array(sampled.output)
    else:
        seq_string = np.array([f"{a}{b}" for a, b in zip(sampled.input, sampled.output)])

    sampled.items1 = np.array(sampled.items1)
    # order shouldn't matter here
    smilies, uniq_idx = np.unique(seq_string, return_index=True)

    sampled.items1 = list(sampled.items1[uniq_idx])
    sampled.output = list(smilies)
    sampled.nlls = sampled.nlls[uniq_idx]
    sampled.items2 = list(np.array(sampled.items2)[uniq_idx])
    sampled.input = sampled.items1

    if orig_len > len(sampled.output):
        logger.debug(f"Removed {orig_len - len(sampled.output)} duplicate sequences")

    return sampled


def validate_smiles(mols: List[Chem.Mol], isomeric: bool = False) -> Tuple[List, np.ndarray]:
    """Basic validation of sampled or joined SMILES

    The molecules are converted to canonical SMILES.  Each SMILES state is
    determined to be invalid, valid or duplicate.

    :returns: validated SMILES and their states
    """

    validated_smilies = []
    smilies_states = []  # valid, invalid, duplicate
    seen_before = set()

    for i, mol in enumerate(mols):
        if mol:
            failed = Chem.SanitizeMol(mol, catchErrors=True)

            if not failed:
                canonical_smiles = Chem.MolToSmiles(
                    mol, canonical=True, isomericSmiles=isomeric
                )

                if canonical_smiles in seen_before:
                    smilies_states.append(SmilesState.DUPLICATE)
                else:
                    smilies_states.append(SmilesState.VALID)

                validated_smilies.append(canonical_smiles)
                seen_before.add(canonical_smiles)
            else:
                validated_smilies.append(f"{INVALID_STR}{i}")
                smilies_states.append(SmilesState.INVALID)
        else:
            validated_smilies.append(f"{INVALID_STR}{i}")
            smilies_states.append(SmilesState.INVALID)

    smilies_states = np.array(smilies_states)

    return validated_smilies, smilies_states

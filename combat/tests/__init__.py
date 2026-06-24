"""
combat 模块单元测试
==================
测试覆盖: Buff系统 / Fighter 属性&伤害 / CombatSim 战斗循环 / Skill 解析

运行: python -m pytest combat/tests/ -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

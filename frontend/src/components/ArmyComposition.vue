<template>
  <div v-if="groups.length" class="army-composition">
    <div v-for="group in groups" :key="group.key" class="army-composition__row">
      <span class="army-composition__label">{{ group.label }}</span>
      <div class="army-composition__units">
        <ArmyUnitIcon
          v-for="unit in previewUnits(group)"
          :key="`${group.key}-${unit.kind}-${unit.id}`"
          :unit="unit"
        />
        <span v-if="hiddenCount(group)" class="army-composition__more">
          +{{ hiddenCount(group) }}
        </span>
      </div>
    </div>

    <button
      type="button"
      class="army-composition__toggle"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起详情' : '详情' }}
      <span class="army-composition__chevron" :class="{ 'is-open': expanded }">▾</span>
    </button>

    <div v-if="expanded" class="army-composition__detail">
      <section v-for="group in groups" :key="group.key" class="army-composition__group">
        <h4 class="army-composition__group-title">{{ group.label }}</h4>
        <ul class="army-composition__list">
          <li v-for="unit in group.units" :key="`${unit.kind}-${unit.id}`" class="army-composition__item">
            <ArmyUnitIcon
              v-if="unit.kind !== 'equipment'"
              :unit="unit"
              :show-count="false"
              class="army-composition__item-icon"
            />
            <span v-else class="army-composition__dot" aria-hidden="true"></span>
            <span class="army-composition__name">{{ unit.name }}</span>
            <span v-if="unit.kind === 'pet'" class="army-composition__tag">战宠</span>
            <span v-else-if="unit.kind === 'equipment'" class="army-composition__tag">装备</span>
            <span class="army-composition__count">×{{ unit.count }}</span>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { parseArmyShareCode, type ArmyGroup } from '../data/armyComposition'
import ArmyUnitIcon from './ArmyUnitIcon.vue'

const props = defineProps<{ shareCode: string }>()

const expanded = ref(false)
const groups = computed(() => parseArmyShareCode(props.shareCode))

/** 部队最多先放 10 个，其余用 +N 收起来；详情里给全量。 */
const TROOP_PREVIEW_LIMIT = 10

function previewUnits(group: ArmyGroup) {
  if (group.key === 'heroes') {
    // 装备图很大（单张可达数 MB），预览只放英雄与战宠
    return group.units.filter((unit) => unit.kind !== 'equipment')
  }
  if (group.key === 'troops') {
    return group.units.slice(0, TROOP_PREVIEW_LIMIT)
  }
  return group.units
}

function hiddenCount(group: ArmyGroup): number {
  return Math.max(0, group.units.length - previewUnits(group).length)
}
</script>

<style scoped>
.army-composition {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.army-composition__row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.army-composition__label {
  flex-shrink: 0;
  width: 2.2rem;
  padding-top: 13px;
  color: var(--text-faint);
  font-size: 0.75rem;
}

.army-composition__units {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.army-composition__more {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 44px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--surface-subtle);
  color: var(--text-secondary);
  font-size: 0.75rem;
}

.army-composition__toggle {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 2.4rem;
  padding: 0;
  border: 0;
  background: none;
  color: var(--accent-gold);
  font: inherit;
  font-size: 0.8125rem;
  cursor: pointer;
}

.army-composition__toggle:hover {
  color: var(--accent-gold-bright);
}

.army-composition__chevron {
  display: inline-block;
  transition: transform 0.15s ease;
}

.army-composition__chevron.is-open {
  transform: rotate(180deg);
}

.army-composition__detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 2px;
  padding: 10px 12px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: #0000002e;
}

.army-composition__group-title {
  margin: 0 0 6px;
  color: var(--text-secondary);
  font-size: 0.75rem;
  font-weight: 600;
}

.army-composition__list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.army-composition__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-primary);
  font-size: 0.8125rem;
}

.army-composition__item-icon {
  width: 26px;
  height: 26px;
  border-radius: 6px;
}

.army-composition__item-icon :deep(.army-unit__image) {
  padding: 2px;
}

.army-composition__dot {
  width: 7px;
  height: 7px;
  margin: 0 4px 0 2px;
  border-radius: 50%;
  background: var(--accent-gold);
}

.army-composition__name {
  white-space: nowrap;
}

.army-composition__tag {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--surface-subtle);
  color: var(--text-faint);
  font-size: 0.6875rem;
  line-height: 16px;
}

.army-composition__count {
  color: var(--accent-gold-bright);
  font-size: 0.75rem;
  font-weight: 600;
}
</style>

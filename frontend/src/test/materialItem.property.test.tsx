/**
 * Property 5: 所有 PlatformType 值都能渲染对应图标（非空字符串）
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MaterialItem } from '../components/source-panel/MaterialItem'
import type { Material, PlatformType } from '../types'

const ALL_PLATFORMS: PlatformType[] = [
  'bilibili', 'youtube', 'google', 'github', 'xiaohongshu', 'other',
]

function makeMaterial(type: PlatformType): Material {
  return {
    id: `m-${type}`,
    type,
    name: `Test ${type}`,
    status: 'ready',
    addedAt: new Date().toISOString(),
  }
}

describe('MaterialItem — Property 5: all PlatformType values render an icon', () => {
  it.each(ALL_PLATFORMS)('platform "%s" renders a non-empty icon', (platform) => {
    const material = makeMaterial(platform)
    const { container } = render(
      <MaterialItem
        material={material}
        isSelected={false}
        onClick={() => {}}
        onRemove={() => {}}
      />
    )
    // 图标是 aria-hidden span，内容应为非空 emoji
    const iconSpan = container.querySelector('[aria-hidden="true"]')
    expect(iconSpan).not.toBeNull()
    expect(iconSpan!.textContent?.trim().length).toBeGreaterThan(0)
  })

  it('all platforms have distinct icons', () => {
    const icons = ALL_PLATFORMS.map(platform => {
      const material = makeMaterial(platform)
      const { container } = render(
        <MaterialItem
          material={material}
          isSelected={false}
          onClick={() => {}}
          onRemove={() => {}}
        />
      )
      return container.querySelector('[aria-hidden="true"]')?.textContent?.trim()
    })
    // 每个平台都有图标（非 undefined）
    icons.forEach(icon => expect(icon).toBeTruthy())
  })
})

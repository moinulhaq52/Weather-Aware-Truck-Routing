import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library only auto-cleans with Vitest globals enabled; unmount explicitly between tests.
afterEach(() => cleanup())

// fromHere.tester.test.ts
import pluginTester, { TestObject } from 'babel-plugin-tester';
import { TransformOptions } from '@babel/core';
import fromHerePlugin from './fromHere'; // Adjust path

import { describe, it, expect, beforeAll, afterEach /* etc. */ } from '@jest/globals';

// globalThis.describe = describe;

// Define shared Babel options for clarity
const commonBabelOptions: TransformOptions = {
    configFile: false,
    babelrc: false,
};

// Define the tests using the TestObject type for better intellisense (optional)
const tests: Record<string, TestObject | string> = {
    'removes code before and keeps used variables': {
        code: `
      function processData(inputParam, threshold) {
        const intermediateResult = inputParam * 2; // Keep
        const unusedData = { value: 100 }; // Remove
        let counter = 0; // Remove
        const configValue = threshold + 5; // Keep
        function unusedHelper() {} // Remove
        function processFurther(data) { return data / configValue; } // Keep

        console.log("Initial processing done."); // Remove

        fromHere(); // The marker

        console.log("Starting final processing."); // Keep
        const finalResult = processFurther(intermediateResult); // Keep
        console.log(\`Final result based on threshold \${configValue}:\`, finalResult); // Keep
        console.log("Input param was:", inputParam); // Keep
        return finalResult > 1; // Keep
      }
    `,
        // babel-plugin-tester often uses prettier, making output comparison robust
        output: `
      function processData(inputParam, threshold) {
        const intermediateResult = inputParam * 2;
        const configValue = threshold + 5;
        // Remove
        function processFurther(data) {
          return data / configValue;
        } // Keep

        // The marker

        console.log("Starting final processing."); // Keep
        const finalResult = processFurther(intermediateResult); // Keep
        console.log(\`Final result based on threshold \${configValue}:\`, finalResult); // Keep
        console.log("Input param was:", inputParam); // Keep
        return finalResult > 1; // Keep
      }
    `,
    },

    'no change if marker is absent': `
    function simple(a) {
      const b = a + 1;
      console.log(b);
      return b;
    }
  `, // Providing only 'code' implies input and output are the same (after formatting)

    'throws on multiple markers': {
        code: `
      function multiple(a) {
        fromHere();
        console.log(a);
        fromHere();
        return a;
      }
    `,
        // Use 'error' to assert that the plugin throws
        error: /Multiple fromHere\(\) calls found/,
    },

    // Example using fixtures (assuming files exist)
    // 'basic fixture test': {
    //   fixture: path.join(__dirname, 'fixtures/input.js'),
    //   outputFixture: path.join(__dirname, 'fixtures/output.js'),
    // }
};

// Run the tests
pluginTester({
    plugin: fromHerePlugin,
    pluginName: 'transform-from-here',
    babelOptions: commonBabelOptions,
    tests: tests, // Pass the defined tests object
});

// https://www.npmjs.com/package/babel-plugin-tester#built-in-debugging-support
// NODE_ENV='test' DEBUG='babel-plugin-tester,babel-plugin-tester:*' DEBUG_DEPTH='1'
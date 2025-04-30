// babel-plugin-variable-labels.js
import * as t from '@babel/types';

// Helper to check if a node is the label declaration pattern
function isLabelDeclaration(node) {
    return (
        t.isVariableDeclaration(node) &&
        node.declarations.length === 1 &&
        t.isVariableDeclarator(node.declarations[0]) &&
        t.isIdentifier(node.declarations[0].id) &&
        t.isCallExpression(node.declarations[0].init) &&
        t.isIdentifier(node.declarations[0].init.callee, { name: 'label' })
    );
}

// Helper to check if a node is the goto call pattern
function isGotoCall(node) {
    return (
        t.isCallExpression(node) &&
        t.isIdentifier(node.callee, { name: 'goto' }) &&
        node.arguments.length === 1 &&
        t.isIdentifier(node.arguments[0]) // Expecting the label variable identifier
    );
}

export default function ({ types: t }) {
    return {
        name: 'transform-variable-labels',
        visitor: {
            Function(path) {
                const labels = new Map(); // Map label variable name -> { stateName: string, startNodePath: NodePath | null }
                const gotos = []; // Store { path: NodePath, targetLabelVar: string }
                const labelDeclarationPaths = []; // Store paths to remove label declarations

                let hasGoto = false;
                let hasLabel = false;

                // --- Step 1: Scan for labels and gotos ---
                const functionBodyPath = path.get('body');
                if (!functionBodyPath.isBlockStatement()) {
                    // Only transform functions with block statements
                    return;
                }

                const bodyPaths = functionBodyPath.get('body');

                for (let i = 0; i < bodyPaths.length; i++) {
                    const nodePath = bodyPaths[i];
                    const node = nodePath.node;

                    if (isLabelDeclaration(node)) {
                        const labelVarName = node.declarations[0].id.name;
                        if (labels.has(labelVarName)) {
                            throw nodePath.buildCodeFrameError(
                                `Duplicate label variable '${labelVarName}'`
                            );
                        }
                        const stateName = path.scope.generateUidIdentifier(labelVarName)
                            .name;
                        // The code block for this label starts *after* the declaration
                        const startNodePath = bodyPaths[i + 1] || null; // Get the next statement's path
                        labels.set(labelVarName, { stateName, startNodePath });
                        labelDeclarationPaths.push(nodePath); // Mark for removal
                        hasLabel = true;
                    } else if (t.isExpressionStatement(node) && isGotoCall(node.expression)) {
                        const targetLabelVar = node.expression.arguments[0].name;
                        gotos.push({ path: nodePath, targetLabelVar });
                        hasGoto = true;
                    } else {
                        // Also traverse into nested blocks if necessary, simplified here
                        nodePath.traverse({
                            CallExpression(callPath) {
                                if (isGotoCall(callPath.node)) {
                                    const targetLabelVar = callPath.node.arguments[0].name;
                                    gotos.push({ path: callPath, targetLabelVar });
                                    hasGoto = true;
                                }
                            }
                        });
                    }
                }

                // If no relevant constructs found, exit
                if (!hasGoto && !hasLabel) {
                    return;
                }
                if (hasGoto && !hasLabel) {
                    throw path.buildCodeFrameError(
                        'Found goto() calls but no label variable declarations in the function.'
                    );
                }

                // --- Step 2: Prepare for State Machine ---
                const stateVar = path.scope.generateUidIdentifier('gotoState');
                const startState = 'start';
                const endState = 'end';

                // Validate goto targets
                for (const g of gotos) {
                    if (!labels.has(g.targetLabelVar)) {
                        throw g.path.buildCodeFrameError(
                            `Undefined label variable '${g.targetLabelVar}' used in goto()`
                        );
                    }
                }

                // --- Step 3: Transform Gotos and Returns (in place before restructuring) ---
                path.traverse({
                    // Replace goto(labelVar)
                    CallExpression(callPath) {
                        if (isGotoCall(callPath.node)) {
                            const targetLabelVar = callPath.node.arguments[0].name;
                            const targetState = labels.get(targetLabelVar)?.stateName;
                            if (!targetState) {
                                // Should have been caught earlier, but double-check
                                throw callPath.buildCodeFrameError(`Internal error: Cannot find state for label ${targetLabelVar}`);
                            }
                            // _gotoState = 'targetState'; continue;
                            // If goto is inside an ExpressionStatement, replace the whole statement
                            if (callPath.parentPath.isExpressionStatement()) {
                                callPath.parentPath.replaceWithMultiple([
                                    t.expressionStatement(t.assignmentExpression('=', stateVar, t.stringLiteral(targetState))),
                                    t.continueStatement()
                                ]);
                            } else {
                                // If it's part of a larger expression (less likely for goto), this needs more complex handling.
                                // Replacing just the call expression might be syntactically invalid.
                                // For simplicity, assume goto is a standalone statement.
                                callPath.replaceWithMultiple([ // This might error if not in a statement context
                                    t.expressionStatement(t.assignmentExpression('=', stateVar, t.stringLiteral(targetState))),
                                    t.continueStatement()
                                ]);
                            }
                        }
                    },
                    // Replace return statements
                    ReturnStatement(returnPath) {
                        // Simplified: Doesn't handle storing return value properly yet.
                        // Needs a variable outside the loop to store the return value.
                        returnPath.replaceWithMultiple([
                            t.expressionStatement(t.assignmentExpression('=', stateVar, t.stringLiteral(endState))),
                            t.continueStatement(),
                        ]);
                        returnPath.skip();
                    }
                });

                // --- Step 4: Remove Label Declarations ---
                labelDeclarationPaths.forEach(p => p.remove());

                // --- Step 5: Build the State Machine Structure ---
                const switchCases = [];
                const originalNodes = functionBodyPath.node.body; // Get potentially modified nodes

                // Group nodes by state
                const nodesByState = new Map(); // Map stateName -> nodes[]
                nodesByState.set(startState, []);

                let currentStateNodes = nodesByState.get(startState);
                let currentLabelVarForState = null;

                // Find the state associated with each node
                const stateForNode = new Map(); // Map node -> stateName
                labels.forEach(({ stateName, startNodePath }) => {
                    if (startNodePath) {
                        stateForNode.set(startNodePath.node, stateName);
                    }
                });

                // Iterate through the *current* nodes in the body after transformations/removals
                functionBodyPath.get('body').forEach(nodePath => {
                    const node = nodePath.node;
                    const designatedState = stateForNode.get(node);

                    if (designatedState) {
                        // Start of a new labeled block
                        currentStateNodes = [];
                        nodesByState.set(designatedState, currentStateNodes);
                    }
                    if (currentStateNodes) { // Ensure we have a place to put the node
                        currentStateNodes.push(node);
                    } else {
                        // This might happen if the first statement was a label declaration
                        // and got removed. Add to start state as fallback.
                        nodesByState.get(startState).push(node);
                        currentStateNodes = nodesByState.get(startState);
                    }
                });


                // Create switch cases from grouped nodes
                // Start state first
                switchCases.push(
                    t.switchCase(t.stringLiteral(startState), nodesByState.get(startState))
                );

                // Then label states
                labels.forEach(({ stateName }) => {
                    const caseBody = nodesByState.get(stateName) || [];
                    // Add fallthrough logic (simplified: assume end state unless goto happens)
                    // A real implementation needs better control flow analysis.
                    caseBody.push(t.expressionStatement(t.assignmentExpression('=', stateVar, t.stringLiteral(endState))));
                    caseBody.push(t.continueStatement());

                    switchCases.push(
                        t.switchCase(t.stringLiteral(stateName), caseBody)
                    );
                });

                // Add the end state case
                switchCases.push(
                    t.switchCase(t.stringLiteral(endState), [t.breakStatement()]) // Breaks the while loop
                );

                // Create the loop and new body
                const switchStatement = t.switchStatement(t.identifier(stateVar.name), switchCases);
                const whileLoop = t.whileStatement(t.booleanLiteral(true), t.blockStatement([switchStatement]));

                const newBody = t.blockStatement([
                    t.variableDeclaration('let', [
                        t.variableDeclarator(stateVar, t.stringLiteral(startState)),
                    ]),
                    whileLoop,
                    // Add return statement here if handling return values properly
                ]);

                // --- Step 6: Replace the original function body ---
                functionBodyPath.replaceWith(newBody);
            },
        },
    };
}

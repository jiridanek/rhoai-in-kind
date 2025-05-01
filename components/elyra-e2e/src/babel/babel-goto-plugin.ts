import * as t from '@babel/types';
import type { NodePath, Visitor } from '@babel/traverse';

// Define types for the data structures
interface LabelInfo {
    stateName: string;
    startNodePath: NodePath<t.Statement> | null;
}

interface GotoInfo {
    path: NodePath<t.CallExpression | t.ExpressionStatement>; // Path can be CallExpression or its parent ExpressionStatement
    targetLabelVar: string;
}

// Helper to check if a node is the label declaration pattern
// Add type annotation for the 'node' parameter
function isLabelDeclaration(node: t.Node): node is t.VariableDeclaration {
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
// Add type annotation for the 'node' parameter
function isGotoCall(node: t.Node): node is t.CallExpression {
    return (
        t.isCallExpression(node) &&
        t.isIdentifier(node.callee, { name: 'goto' }) &&
        node.arguments.length === 1 &&
        t.isIdentifier(node.arguments[0]) // Expecting the label variable identifier
    );
}

// Define the Babel plugin function signature
export default function ({ types }: { types: typeof t }): { name: string; visitor: Visitor } {
    return {
        name: 'transform-variable-labels',
        visitor: {
            // Specify the type for the Function node path
            Function(path: NodePath<t.Function>) {
                // Add types for maps and arrays
                const labels = new Map<string, LabelInfo>();
                const gotos: GotoInfo[] = [];
                const labelDeclarationPaths: NodePath<t.VariableDeclaration>[] = []; // Type the array of paths

                let hasGoto = false;
                let hasLabel = false;

                // --- Step 1: Scan for labels and gotos ---
                const functionBodyPath = path.get('body');
                if (!functionBodyPath.isBlockStatement()) {
                    // Only transform functions with block statements
                    return;
                }

                // Type the array of statement paths
                const bodyPaths: NodePath<t.Statement>[] = functionBodyPath.get('body');

                for (let i = 0; i < bodyPaths.length; i++) {
                    const nodePath = bodyPaths[i];
                    const node = nodePath.node;

                    if (isLabelDeclaration(node)) {
                        // node is now narrowed to t.VariableDeclaration
                        const labelVarName = (node.declarations[0].id as t.Identifier).name; // Assert type if needed, though check implies it
                        if (labels.has(labelVarName)) {
                            throw nodePath.buildCodeFrameError(
                                `Duplicate label variable '${labelVarName}'`
                            );
                        }
                        const stateName = path.scope.generateUidIdentifier(labelVarName)
                            .name;
                        // The code block for this label starts *after* the declaration
                        const startNodePath = bodyPaths[i + 1] || null; // Type is NodePath<t.Statement> | null
                        labels.set(labelVarName, { stateName, startNodePath });
                        labelDeclarationPaths.push(nodePath as NodePath<t.VariableDeclaration>); // Cast if sure, or refine isLabelDeclaration return
                        hasLabel = true;
                    } else if (t.isExpressionStatement(node) && isGotoCall(node.expression)) {
                        // node.expression is now narrowed to t.CallExpression
                        const targetLabelVar = (node.expression.arguments[0] as t.Identifier).name; // Assert type
                        gotos.push({ path: nodePath as NodePath<t.ExpressionStatement>, targetLabelVar }); // Cast path
                        hasGoto = true;
                    } else {
                        // Also traverse into nested blocks if necessary, simplified here
                        nodePath.traverse({
                            // Type the call expression path
                            CallExpression(callPath: NodePath<t.CallExpression>) {
                                if (isGotoCall(callPath.node)) {
                                    // callPath.node is narrowed to t.CallExpression
                                    const targetLabelVar = (callPath.node.arguments[0] as t.Identifier).name; // Assert type
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
                const stateVar = path.scope.generateUidIdentifier('gotoState'); // Type is t.Identifier
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
                    // Type the call expression path
                    CallExpression(callPath: NodePath<t.CallExpression>) {
                        if (isGotoCall(callPath.node)) {
                            // callPath.node is narrowed
                            const targetLabelVar = (callPath.node.arguments[0] as t.Identifier).name;
                            const targetState = labels.get(targetLabelVar)?.stateName;
                            if (!targetState) {
                                throw callPath.buildCodeFrameError(`Internal error: Cannot find state for label ${targetLabelVar}`);
                            }

                            const parentPath = callPath.parentPath; // Get parent path for check
                            if (parentPath.isExpressionStatement()) {
                                parentPath.replaceWithMultiple([
                                    t.expressionStatement(t.assignmentExpression('=', stateVar, t.stringLiteral(targetState))),
                                    t.continueStatement()
                                ]);
                            } else {
                                // Handle the case where goto might not be in a simple ExpressionStatement
                                // This simplified version might still cause issues if goto is nested deeply
                                console.warn("Replacing goto() call that is not a direct ExpressionStatement. This might lead to unexpected behavior or errors.");
                                callPath.replaceWithMultiple([
                                    t.expressionStatement(t.assignmentExpression('=', stateVar, t.stringLiteral(targetState))),
                                    t.continueStatement()
                                ]);
                            }
                            // It's generally safer to skip further traversal on the replaced path
                            // callPath.skip(); // Consider adding this if replacements cause issues
                        }
                    },
                    // Type the return statement path
                    ReturnStatement(returnPath: NodePath<t.ReturnStatement>) {
                        // Simplified: Doesn't handle storing return value properly yet.
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
                const switchCases: t.SwitchCase[] = [];

                // Group nodes by state
                const nodesByState = new Map<string, t.Statement[]>();
                nodesByState.set(startState, []);

                let currentStateNodes: t.Statement[] | undefined = nodesByState.get(startState);

                // Find the state associated with each node
                const stateForNode = new Map<t.Node, string>(); // Map Node -> stateName
                labels.forEach(({ stateName, startNodePath }) => {
                    if (startNodePath) {
                        // Use startNodePath.node which is guaranteed to be a t.Statement here
                        stateForNode.set(startNodePath.node, stateName);
                    }
                });

                // Iterate through the *current* nodes in the body after transformations/removals
                // Use functionBodyPath which is guaranteed to be a BlockStatement path
                functionBodyPath.get('body').forEach(nodePath => {
                    const node = nodePath.node;
                    const designatedState = stateForNode.get(node);

                    if (designatedState) {
                        // Start of a new labeled block
                        currentStateNodes = [];
                        nodesByState.set(designatedState, currentStateNodes);
                    }

                    // Check if currentStateNodes is defined before pushing
                    if (currentStateNodes) {
                        currentStateNodes.push(node);
                    } else {
                        // Fallback: Add to start state if no current state is defined
                        // This condition might indicate an issue if it happens unexpectedly
                        console.warn("Node added to 'start' state as fallback:", node);
                        const startNodes = nodesByState.get(startState);
                        if (startNodes) {
                            startNodes.push(node);
                            currentStateNodes = startNodes; // Reassign currentStateNodes
                        } else {
                            // This should ideally not happen if startState is initialized
                            console.error("Critical error: 'start' state node list not found.");
                        }
                    }
                });


                // Create switch cases from grouped nodes
                // Start state first
                switchCases.push(
                    t.switchCase(t.stringLiteral(startState), nodesByState.get(startState) || []) // Provide default empty array
                );

                // Then label states
                labels.forEach(({ stateName }) => {
                    const caseBody = nodesByState.get(stateName) || [];
                    // Add fallthrough logic (simplified)
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
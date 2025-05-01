import * as t from '@babel/types';
import traverse, { NodePath, Visitor, Scope, Binding } from '@babel/traverse';

// Helper to check if a node is the fromHere() call statement
// Uses a type predicate to narrow down the type in calling scopes
function isFromHereStatement(node: t.Node): node is t.ExpressionStatement {
    return (
        t.isExpressionStatement(node) &&
        t.isCallExpression(node.expression) &&
        t.isIdentifier(node.expression.callee, { name: 'fromHere' }) &&
        node.expression.arguments.length === 0
    );
}

// Define the structure for the Babel plugin export
interface PluginDefinition {
    name: string;
    visitor: Visitor;
}

export default function ({ types }: { types: typeof t }): PluginDefinition {
    return {
        name: 'transform-from-here',
        visitor: {
            Function(path: NodePath<t.Function>) {
                const functionBodyPath = path.get('body');

                // Ensure we are working with a function that has a BlockStatement body
                if (!functionBodyPath.isBlockStatement()) {
                    // Check if the node is a type that can have an 'id' before accessing it
                    const functionName = (t.isFunctionDeclaration(path.node) || t.isFunctionExpression(path.node))
                        ? path.node.id?.name // Access id only if it's FunctionDeclaration or FunctionExpression
                        : null; // Arrow functions don't have an id

                    console.warn(`Skipping function '${functionName ?? 'anonymous'}' as it does not have a block statement body.`);
                    return;
                }

                const bodyPaths: NodePath<t.Statement>[] = functionBodyPath.get('body');
                let fromHereIndex: number = -1;
                let fromHerePath: NodePath<t.Statement> | null = null;

                // --- Step 1: Find the fromHere() marker ---
                for (let i = 0; i < bodyPaths.length; i++) {
                    const currentPath = bodyPaths[i];
                    if (isFromHereStatement(currentPath.node)) {
                        if (fromHereIndex !== -1) {
                            // Throw an error if multiple markers are found
                            throw currentPath.buildCodeFrameError(
                                'Multiple fromHere() calls found in the same function scope. Only one is allowed.'
                            );
                        }
                        fromHereIndex = i;
                        fromHerePath = currentPath; // Store the path
                    }
                }

                // If no marker found, exit processing for this function
                if (fromHereIndex === -1 || !fromHerePath) {
                    return;
                }

                // --- Step 2: Split statements ---
                const beforeStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(0, fromHereIndex);
                // Create a Set of the actual nodes for faster/more reliable lookup
                const beforeStatementNodes = new Set(beforeStatementsPaths.map(p => p.node));
                const afterStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(fromHereIndex + 1);

                // --- Step 3: Analyze variable usage AFTER fromHere() ---
                const usedVariableNames = new Set<string>();
                const afterStatementsBlock: t.BlockStatement = t.blockStatement(
                    afterStatementsPaths.map(p => p.node)
                );

                traverse(afterStatementsBlock, {
                    Identifier(identifierPath: NodePath<t.Identifier>) {
                        if (!identifierPath.isReferencedIdentifier()) {
                            return;
                        }

                        const identifierName = identifierPath.node.name;
                        const binding = path.scope.getBinding(identifierName);

                        if (binding && binding.scope === path.scope) {
                            let declarationStatementPath: NodePath | null = binding.path;
                            while (declarationStatementPath && !declarationStatementPath.isStatement()) {
                                declarationStatementPath = declarationStatementPath.parentPath;
                            }

                            // --- Add Detailed Logging ---
                            if (identifierName === 'intermediateResult' || identifierName === 'configValue') {
                                console.log(`[DEBUG] Checking identifier: ${identifierName}`);
                                if (declarationStatementPath) {
                                    console.log(`[DEBUG]   Declaration Node Type: ${declarationStatementPath.node.type}`);
                                    const isInBeforeSet = beforeStatementNodes.has(declarationStatementPath.node);
                                    console.log(`[DEBUG]   Is declaration node in beforeStatementNodes? ${isInBeforeSet}`);
                                    if (!isInBeforeSet) {
                                        // If it's not found, let's log the nodes for comparison
                                        console.log('[DEBUG]   Declaration Node:', declarationStatementPath.node);
                                        console.log('[DEBUG]   Nodes in beforeStatementNodes:', Array.from(beforeStatementNodes));
                                    }
                                } else {
                                    console.log('[DEBUG]   Could not find declaration statement path.');
                                }
                            }
                            // --- End Detailed Logging ---

                            if (declarationStatementPath && beforeStatementNodes.has(declarationStatementPath.node)) {
                                usedVariableNames.add(identifierName);
                            }
                        }
                    },
                    // ... CallExpression visitor remains the same ...
                }, path.scope, {}, functionBodyPath);

                // --- Add Logging for the final set ---
                console.log('[DEBUG] Final usedVariableNames:', Array.from(usedVariableNames));
                // --- End Logging ---

                // --- Step 4: Identify necessary declarations BEFORE fromHere() ---
                const necessaryDeclarationNodes: t.Statement[] = [];
                const addedDeclarations = new Set<t.Node>(); // Prevent adding the same statement node multiple times

                beforeStatementsPaths.forEach(statementPath => {
                    let declarationNodeToAdd: t.Statement | null = null;

                    // Check for Variable Declarations (const, let, var)
                    if (statementPath.isVariableDeclaration()) {
                        const necessaryDeclarators: t.VariableDeclarator[] = [];
                        statementPath.node.declarations.forEach(declarator => {
                            // Get the map of binding identifiers
                            // The map looks like { Identifier?: Identifier[], AssignmentPattern?: AssignmentPattern[], ... }
                            const identifiersMap = t.getBindingIdentifiers(declarator.id);

                            // Iterate over the arrays within the map's values
                            for (const nodeArray of Object.values(identifiersMap)) {
                                // nodeArray is expected to be an array like t.Identifier[] or t.AssignmentPattern[] etc.
                                // Add a check to be safe, although Object.values should always return arrays here.
                                if (Array.isArray(nodeArray)) {
                                    // Iterate over the nodes within this specific array
                                    nodeArray.forEach((node: t.Node | null) => { // node could be Identifier, Pattern, etc. or null
                                        // Check if the node is a valid Identifier and is used
                                        if (node && t.isIdentifier(node) && usedVariableNames.has(node.name)) {
                                            // If this identifier is used, keep the entire declarator it came from.
                                            // We only need to add the declarator once, even if it binds multiple used variables.
                                            if (!necessaryDeclarators.includes(declarator)) {
                                                necessaryDeclarators.push(declarator);
                                            }
                                            // Optimization: If we found one used identifier, we keep the whole declarator,
                                            // no need to check other identifiers within the *same* declarator.
                                            // However, the current logic correctly handles this by checking includes().
                                        }
                                        // Add checks here for other node types (like patterns) if necessary
                                    });
                                }
                            }
                        });

                        // If any declarators from this statement are needed, reconstruct the declaration
                        if (necessaryDeclarators.length > 0) {
                            // Create a new declaration statement with only the necessary variables
                            declarationNodeToAdd = t.variableDeclaration(
                                statementPath.node.kind, // Keep original kind (const/let/var)
                                necessaryDeclarators // Use the collected necessary declarators
                            );
                        }
                    }
                    // Check for Function Declarations
                    else if (statementPath.isFunctionDeclaration()) {
                        // Function declarations are hoisted, but we check usage explicitly
                        if (statementPath.node.id && usedVariableNames.has(statementPath.node.id.name)) {
                            declarationNodeToAdd = statementPath.node;
                        }
                    }
                    // Check for Class Declarations
                    else if (statementPath.isClassDeclaration()) {
                        if (statementPath.node.id && usedVariableNames.has(statementPath.node.id.name)) {
                            declarationNodeToAdd = statementPath.node;
                        }
                    }

                    // Add the necessary declaration node if found and not already added
                    if (declarationNodeToAdd && !addedDeclarations.has(declarationNodeToAdd)) {
                        necessaryDeclarationNodes.push(declarationNodeToAdd);
                        addedDeclarations.add(declarationNodeToAdd);
                    }
                });

                // --- Step 5: Construct the new function body ---
                // Combine the preserved declarations with all statements that came after the marker
                const newBodyStatements: t.Statement[] = [
                    ...necessaryDeclarationNodes,
                    ...afterStatementsPaths.map(p => p.node)
                ];

                // --- Step 6: Replace the body ---
                functionBodyPath.replaceWith(t.blockStatement(newBodyStatements));

                // Optional: Re-crawl the scope if further analysis depends on the modified structure
                // path.scope.crawl();
            },
        },
    };
}
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
                    console.warn(`Skipping function '${(path.node.id?.name) ?? 'anonymous'}' as it does not have a block statement body.`);
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
                // Statements before the marker (exclusive of the marker)
                const beforeStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(0, fromHereIndex);
                // Statements after the marker (exclusive of the marker)
                const afterStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(fromHereIndex + 1);

                // --- Step 3: Analyze variable usage AFTER fromHere() ---
                const usedVariableNames = new Set<string>();
                // Create a temporary BlockStatement node containing only the 'after' statements
                // This allows isolated traversal for usage analysis
                const afterStatementsBlock: t.BlockStatement = t.blockStatement(
                    afterStatementsPaths.map(p => p.node)
                );

                // Traverse the 'after' block to find all referenced identifiers
                // We need a valid NodePath context for traversal; using the function body's path
                // and providing the function's scope ensures correct binding resolution.
                traverse(afterStatementsBlock, {
                    // Process identifiers that are read/referenced
                    Identifier(identifierPath: NodePath<t.Identifier>) {
                        // Check if it's a reference (not a declaration, label, or property name)
                        if (!identifierPath.isReferencedIdentifier()) {
                            return;
                        }

                        const identifierName = identifierPath.node.name;
                        // Check if the binding exists in the *function's* scope or higher
                        // This avoids counting variables declared *within* the 'after' block itself
                        const binding: Binding | undefined = path.scope.getBinding(identifierName);

                        // We are interested in variables declared *within* the current function
                        // (as parameters or via var/let/const/function/class declarations)
                        // or variables from outer scopes (which are implicitly kept).
                        // We specifically need to track those declared *before* fromHere().
                        if (binding) {
                            // Check if the binding originates from within this function's scope
                            // or is a parameter. We don't need to explicitly preserve bindings
                            // from outer scopes, as they aren't removed.
                            if (binding.path.scope === path.scope) {
                                usedVariableNames.add(identifierName);
                            }
                        } else {
                            // If no binding found in the function scope or above, it might be a global
                            // or an undeclared variable. We don't track these for preservation
                            // within this plugin's logic.
                        }
                    },
                    // Consider function declarations called after fromHere
                    CallExpression(callPath: NodePath<t.CallExpression>) {
                        const callee = callPath.node.callee;
                        // Check if the callee is an identifier and is referenced
                        if (t.isIdentifier(callee) && callPath.get('callee').isReferencedIdentifier()) {
                            const calleeName = callee.name;
                            const binding: Binding | undefined = path.scope.getBinding(calleeName);
                            // If it's bound to a function declared within this function's scope
                            if (binding && binding.path.isFunctionDeclaration() && binding.path.scope === path.scope) {
                                usedVariableNames.add(calleeName);
                            }
                        }
                    }
                }, path.scope, {}, functionBodyPath); // Provide scope and parent path for context


                // --- Step 4: Identify necessary declarations BEFORE fromHere() ---
                const necessaryDeclarationNodes: t.Statement[] = [];
                const addedDeclarations = new Set<t.Node>(); // Prevent adding the same statement node multiple times

                beforeStatementsPaths.forEach(statementPath => {
                    let declarationNodeToAdd: t.Statement | null = null;

                    // Check for Variable Declarations (const, let, var)
                    if (statementPath.isVariableDeclaration()) {
                        const necessaryDeclarators: t.VariableDeclarator[] = [];
                        statementPath.node.declarations.forEach(declarator => {
                            // Check all types of declaration IDs (Identifier, ObjectPattern, ArrayPattern)
                            t.getBindingIdentifiers(declarator.id).forEach(id => {
                                if (usedVariableNames.has(id.name)) {
                                    // If any variable in this declaration is used, keep the declarator
                                    necessaryDeclarators.push(declarator);
                                }
                            });
                        });

                        // If any declarators from this statement are needed, reconstruct the declaration
                        if (necessaryDeclarators.length > 0) {
                            // Create a new declaration statement with only the necessary variables
                            // Note: This splits declarations like 'const a=1, b=2;' if only 'b' is needed.
                            declarationNodeToAdd = t.variableDeclaration(
                                statementPath.node.kind, // Keep original kind (const/let/var)
                                // Filter unique declarators (in case multiple bindings point to the same one)
                                [...new Set(necessaryDeclarators)]
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